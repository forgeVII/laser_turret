"""Offline ESP32 WiFi->UART bridge test.

Run this while the PC is joined to the ESP32 SoftAP "TURRET_LINK". The bridge
is fixed at 192.168.4.1:8888 - no hotspot, no discovery. It needs no internet
and no extra packages - just plain Python.

  cd C:\\learning\\projects\\embedded\\laser_turret\\simulation
  python test_bridge.py

Results are saved to bridge_test_result.txt next to this file.
Keep the PC on TURRET_LINK afterwards, then show me the log.
"""

import os
import socket
import time
from common.turret_link import TURRET_HOST, TURRET_PORT

PORT = TURRET_PORT
HOST = TURRET_HOST
print(f"[Test] bridge = {HOST}:{PORT}", flush=True)
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "bridge_test_result.txt")


def drain(sock):
    sock.setblocking(False)
    try:
        while True:
            if not sock.recv(4096):
                break
    except (BlockingIOError, ConnectionResetError):
        pass
    finally:
        sock.setblocking(True)
        sock.settimeout(0.4)


def ask(sock, cmd, wait, label):
    drain(sock)
    sock.sendall((cmd + "\n").encode("utf-8"))
    time.sleep(wait)
    buf = b""
    sock.settimeout(0.5)
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
    except socket.timeout:
        pass
    text = buf.decode("utf-8", errors="replace")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines, text


def main():
    lines = []

    def log(msg):
        print(msg, flush=True)
        lines.append(msg)

    try:
        sock = socket.create_connection((HOST, PORT), timeout=3)
        log("TCP connect to %s:%d : OK" % (HOST, PORT))
        sock.settimeout(0.4)

        # H proves both directions through the bridge
        out, _ = ask(sock, "H", 0.8, "help")
        log("H help reply: " + ("OK" if any("turret main" in x for x in out)
                               else "MISSING"))
        for x in out[:3]:
            log("   " + x)

        # baseline (turret may be parked at rest after silence)
        out, _ = ask(sock, "F", 0.5, "baseline")
        pos = [x for x in out if "X=" in x]
        log("baseline F: " + (pos[-1] if pos else "(no pos)"))

        # move, let it finish, then F reveals the settled position
        ask(sock, "S110,60", 9.0, "move")
        out, _ = ask(sock, "F", 0.6, "check")
        pos = [x for x in out if "X=" in x]
        log("after S110,60: " + (pos[-1] if pos else "(no pos)"))

        ask(sock, "S80,75", 6.0, "recentre")
        out, _ = ask(sock, "F", 0.6, "check")
        pos = [x for x in out if "X=" in x]
        log("after S80,75: " + (pos[-1] if pos else "(no pos)"))

        sock.close()
        log("DONE")
    except Exception as e:
        log("ERROR: %s: %s" % (type(e).__name__, e))

    with open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\nSaved: " + LOG, flush=True)


if __name__ == "__main__":
    main()
