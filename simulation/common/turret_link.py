"""Transport for the STM32 turret link.

Two interchangeable transports, same .write(bytes) interface:
  wifi   - ESP32 SoftAP bridge at 192.168.4.1:8888 (fixed, no discovery)
  serial - CP2102 data-only fallback on COM4

The ESP32 is always a TURRET_LINK access point. There is no station/mobile-hotspot
mode and no subnet scan: the PC joins TURRET_LINK (open), and the bridge is reached
directly at 192.168.4.1. The bridge sends "TURRET_LINK_READY" on connect.

Startup retry: the first 12 s use a fast 0.25 s reconnect backoff so a late AP
association or ESP32 boot does not leave the sim showing OFFLINE. After that it
falls back to the 2 s backoff used while running.

The ESP32 is transparent, so the payload is identical in both modes:
  S<pan>,<tilt>\\n   engage
  F\\n               release
"""

import socket
import time

# Fixed by the ESP32 SoftAP. No hotspot IP, ARP sweep, or host cache needed.
TURRET_HOST = "192.168.4.1"
TURRET_PORT = 8888
TURRET_GREETING = b"TURRET_LINK_READY"

CONNECT_TIMEOUT = 0.25
STARTUP_GRACE_S = 12.0
RETRY_STARTUP = 0.25
RETRY_STEADY = 2.0


def verify_host(host=TURRET_HOST, tcp_port=TURRET_PORT, timeout=0.3):
    """True when the fixed bridge answers with the greeting on the TCP port."""
    try:
        s = socket.create_connection((host, tcp_port), timeout=timeout)
        s.settimeout(0.2)
        try:
            hello = s.recv(64)
        except Exception:
            hello = b""
        s.close()
        return TURRET_GREETING in hello
    except Exception:
        return False


def discover_turret_host(tcp_port=TURRET_PORT, timeout=CONNECT_TIMEOUT):
    """Compatibility shim for old test scripts; the bridge IP is no longer found.

    Returns the fixed AP IP only when it actually answers, else None.
    """
    return TURRET_HOST if verify_host(TURRET_HOST, tcp_port, timeout) else None


def load_host():
    """Compatibility shim: the bridge address is fixed now."""
    return TURRET_HOST


def save_host(host):
    """Compatibility shim: no cache is written any more."""
    return None


class TurretLink:
    def __init__(self, mode="wifi", port="COM4", baud=115200,
                 host=TURRET_HOST, tcp_port=TURRET_PORT, heartbeat=0.8):
        self.mode = mode
        self.port = port
        self.baud = baud
        self.host = host
        self.tcp_port = tcp_port
        self.heartbeat = heartbeat

        self._ser = None
        self._sock = None
        self._last = b""
        self._last_tx = 0.0
        self.connected = False
        self._started_at = time.time()
        self._retry_after = 0.0
        self._last_err = None
        self._connect()

    # ---------- connection ----------
    def _connect(self):
        if self.mode == "serial":
            self._connect_serial()
        else:
            self._connect_tcp()

    def _connect_serial(self):
        try:
            import serial
            self._ser = serial.Serial(self.port, self.baud, timeout=0.1)
            self.connected = True
            print(f"[Link] CP2102 serial {self.port} @ {self.baud} OK")
        except Exception as e:
            self._ser = None
            self.connected = False
            print(f"[Link] CP2102 serial {self.port} OFFLINE: {e}")

    def _connect_tcp(self):
        # Do not block the render loop on repeated connects. The first 12 s
        # retry quickly (0.25 s); after that back off to 2 s, and only log
        # state changes so a missing bridge cannot spam the console.
        now = time.time()
        if now < self._retry_after:
            return
        starting = (now - self._started_at) < STARTUP_GRACE_S
        self._retry_after = now + (RETRY_STARTUP if starting else RETRY_STEADY)
        try:
            s = socket.create_connection((self.host, self.tcp_port),
                                         timeout=CONNECT_TIMEOUT)
            s.settimeout(0.05)
            self._sock = s
            self.connected = True
            self._last_err = None
            print(f"[Link] WiFi AP {self.host}:{self.tcp_port} OK")
        except Exception as e:
            self._sock = None
            self.connected = False
            msg = str(e)
            if msg != self._last_err:
                print(f"[Link] WiFi AP {self.host}:{self.tcp_port} waiting "
                      f"for bridge (PC must be on TURRET_LINK): {msg}")
                self._last_err = msg

    def reconnect(self):
        """Force a fresh connect to the fixed bridge (the L key)."""
        self.close()
        self.host = TURRET_HOST
        self._started_at = time.time()
        self._retry_after = 0.0
        self._last_err = None
        self._connect()
        print(f"[Link] reconnecting to {TURRET_HOST}:{self.tcp_port}")

    # ---------- IO ----------
    def write(self, data):
        """Send a command and remember it for the watchdog heartbeat."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._last = data
        self._last_tx = time.time()
        return self._send(data)

    def _send(self, data):
        if self.mode == "serial":
            if self._ser is None:
                self._connect_serial()
            if self._ser is not None:
                try:
                    self._ser.write(data)
                    self.connected = True
                    return True
                except Exception:
                    self.connected = False
                    try:
                        self._ser.close()
                    except Exception:
                        pass
                    self._ser = None
            return False

        if self._sock is None:
            self._connect_tcp()
        if self._sock is not None:
            try:
                self._sock.sendall(data)
                self.connected = True
                return True
            except Exception:
                self.connected = False
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
        return False

    def service(self):
        """Repeat the last command so the STM32 link-loss watchdog stays happy.

        Watchdog: 2s quiet -> laser OFF, position held (no auto rest).
        """
        if not self._last:
            return
        if time.time() - self._last_tx >= self.heartbeat:
            self._send(self._last)
            self._last_tx = time.time()

    def close(self):
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
        self._ser = None
        self._sock = None
        self.connected = False
