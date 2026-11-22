"""ESP32 bridge loopback test - isolates WiFi/TCP from the STM32 UART side.

TEMPORARY WIRING:
  1. Disconnect ESP32 GPIO16 and GPIO17 from the Blue Pill.
  2. Jumper GPIO16 <-> GPIO17 directly on the ESP32.
  3. Stay joined to TURRET_LINK; the bridge is fixed at 192.168.4.1.

If PING is echoed back, the ESP32 bridge is fine and the fault is on the
STM32 side (wiring / power / TX-RX crossing).
"""

import os
import socket
import time
from common.turret_link import TURRET_HOST, TURRET_PORT

PORT = TURRET_PORT
HOST = TURRET_HOST
print(f"[Test] bridge = {HOST}:{PORT}", flush=True)
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "loopback_result.txt")


def main():
    lines = []

    def log(msg):
        print(msg, flush=True)
        lines.append(msg)

    try:
        s = socket.create_connection((HOST, PORT), timeout=3)
        s.settimeout(0.5)
        log("TCP connect: OK")
        s.setblocking(False)
        try:
            while s.recv(4096):
                pass
        except (BlockingIOError, ConnectionResetError):
            pass
        s.setblocking(True)
        s.settimeout(0.5)

        s.sendall(b"PING123\n")
        time.sleep(0.6)
        buf = b""
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
        except socket.timeout:
            pass
        got = buf.decode("utf-8", errors="replace")
        log("echo raw: %r" % got)
        log("VERDICT: " + ("PASS - ESP32 bridge good, check STM32 side"
                           if "PING123" in got else
                           "FAIL - problem is inside ESP32 bridge/config"))
        s.close()
    except Exception as e:
        log("ERROR: %s: %s" % (type(e).__name__, e))

    with open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\nSaved: " + LOG, flush=True)


if __name__ == "__main__":
    main()
