"""
Gamepad Reader — reads USB HID data from the DIY Blue Pill gamepad.
Supports pygame (cross-platform) and hidapi backends.
Reports: 8 axes (X/Y/Z/Rx/Ry/Rz/SliderL/SliderR) + 12 buttons + hat.
"""
import sys

try:
    import pygame
    HAS_PYGAME = True
except ImportError:
    HAS_PYGAME = False

try:
    import hid
    HAS_HIDAPI = True
except ImportError:
    HAS_HIDAPI = False


GAMEPAD_VID = 0x0483  # STMicroelectronics
GAMEPAD_PID = 0x572B  # Custom HID gamepad


class GamepadReader:
    def __init__(self, backend="pygame"):
        self.backend = backend
        self.connected = False
        self.axes = [0.0] * 8
        self.buttons = [0] * 12
        self.hat = 0
        self._pygame_pad = None
        self._hid_device = None

    def connect(self):
        if self.backend == "pygame" and HAS_PYGAME:
            return self._connect_pygame()
        elif self.backend == "hidapi" and HAS_HIDAPI:
            return self._connect_hidapi()
        else:
            print(f"[Gamepad] Backend '{self.backend}' not available.")
            print(f"  pygame: {'installed' if HAS_PYGAME else 'NOT installed'}")
            print(f"  hidapi: {'installed' if HAS_HIDAPI else 'NOT installed'}")
            return False

    def _connect_pygame(self):
        pygame.init()
        pygame.joystick.init()
        count = pygame.joystick.get_count()
        if count == 0:
            print("[Gamepad] No joystick detected via pygame.")
            print("  Make sure gamepad is plugged in and recognized by Windows.")
            return False
        self._pygame_pad = pygame.joystick.Joystick(0)
        self._pygame_pad.init()
        name = self._pygame_pad.get_name()
        print(f"[Gamepad] Connected via pygame: {name}")
        self.connected = True
        return True

    def _connect_hidapi(self):
        try:
            devices = hid.enumerate(GAMEPAD_VID, GAMEPAD_PID)
            if not devices:
                print("[Gamepad] No device found with VID:PID = 0483:572B")
                print("  Checking all HID devices...")
                all_devices = hid.enumerate()
                for d in all_devices:
                    if d.get("usage_page") == 1 and d.get("usage") == 5:
                        print(f"    Found gamepad: {d.get('product_string', 'unknown')}")
                return False
            self._hid_device = hid.Device(path=devices[0]["path"])
            print(f"[Gamepad] Connected via hidapi: {self._hid_device.product}")
            self.connected = True
            return True
        except Exception as e:
            print(f"[Gamepad] hidapi connection failed: {e}")
            return False

    def update(self):
        if not self.connected:
            return False
        if self.backend == "pygame":
            return self._update_pygame()
        elif self.backend == "hidapi":
            return self._update_hidapi()
        return False

    def _update_pygame(self):
        try:
            pygame.event.pump()
            if not self.connected:
                return False

            num_axes = min(self._pygame_pad.get_numaxes(), 8)
            for i in range(num_axes):
                raw = self._pygame_pad.get_axis(i)
                self.axes[i] = round((raw + 1.0) * 127.5, 1)  # map -1..1 to 0..255

            num_btns = min(self._pygame_pad.get_numbuttons(), 12)
            for i in range(num_btns):
                self.buttons[i] = self._pygame_pad.get_button(i)

            hat_count = self._pygame_pad.get_numhats()
            if hat_count > 0:
                hat_val = self._pygame_pad.get_hat(0)
                self.hat = (hat_val[0] + 1) * 3 + (hat_val[1] + 1)

            return True
        except Exception:
            self.connected = False
            return False

    def _update_hidapi(self):
        try:
            data = self._hid_device.read(64, timeout=10)
            if data and len(data) >= 12:
                report_id = data[0]
                if report_id == 1 and len(data) >= 12:
                    btn_raw = data[1] | (data[2] << 8)
                    for i in range(12):
                        self.buttons[i] = (btn_raw >> i) & 1
                    self.hat = (data[3] & 0x0F)
                    for i in range(8):
                        self.axes[i] = float(data[4 + i])
                    return True
            return False
        except Exception:
            self.connected = False
            return False

    def get_axes(self):
        return list(self.axes)

    def get_buttons(self):
        return list(self.buttons)

    def get_hat(self):
        return self.hat

    def disconnect(self):
        if self._pygame_pad:
            try:
                self._pygame_pad.quit()
            except Exception:
                pass
        if self._hid_device:
            try:
                self._hid_device.close()
            except Exception:
                pass
        self.connected = False
        print("[Gamepad] Disconnected.")

    def __del__(self):
        self.disconnect()
