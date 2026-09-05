"""
Manual Mode — keyboard serial input + gamepad sticks.
Type x,y on terminal or use gamepad left stick to move turret.
"""
import sys
import threading


class ManualMode:
    def __init__(self, mcu, gamepad, mapper):
        self.mcu = mcu
        self.gamepad = gamepad
        self.mapper = mapper
        self._serial_thread = None
        self._running = False

    def start(self):
        self._running = True
        self.mapper.reset()
        self._serial_thread = threading.Thread(target=self._serial_input_loop, daemon=True)
        self._serial_thread.start()
        print("[Manual] Mode active.")
        print("  Type x,y in terminal (e.g. 90,45) and press Enter.")
        print("  Or use gamepad left stick to move turret.")
        print("  Right trigger = laser ON, Left trigger = laser OFF.")

    def update(self):
        if self.gamepad and self.gamepad.connected:
            self.gamepad.update()
            axes = self.gamepad.get_axes()
            buttons = self.gamepad.get_buttons()

            pan, tilt = self.mapper.gamepad_stick_to_servo(axes[0], axes[1])
            self.mcu.process_command(f"A:{pan:.1f},{tilt:.1f}")

            if len(buttons) > 5 and buttons[5]:
                self.mcu.process_command("L:1")
            elif len(buttons) > 4 and buttons[4]:
                self.mcu.process_command("L:0")

        self.mcu.update()

    def get_state(self):
        axes = self.gamepad.get_axes() if self.gamepad and self.gamepad.connected else [127.5] * 8
        return {
            "mode": "MANUAL",
            "input": f"Stick: Lx={axes[0]:.0f} Ly={axes[1]:.0f}",
        }

    def _serial_input_loop(self):
        while self._running:
            try:
                line = input()
                if not self._running:
                    break
                line = line.strip()
                if not line:
                    continue
                if line.lower() == "laser on":
                    self.mcu.process_command("L:1")
                elif line.lower() == "laser off":
                    self.mcu.process_command("L:0")
                elif "," in line:
                    parts = line.split(",")
                    x = float(parts[0].strip())
                    y = float(parts[1].strip())
                    self.mcu.process_command(f"A:{x:.1f},{y:.1f}")
                elif line.lower() in ("quit", "exit", "q"):
                    self._running = False
            except EOFError:
                break
            except ValueError:
                print("[Manual] Invalid input. Use: x,y (e.g. 90,45)")

    def stop(self):
        self._running = False
        print("[Manual] Stopped.")
