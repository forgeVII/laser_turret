"""
Head Tracking Mode — gamepad MPU6050 orientation controls turret.
Point the gamepad, laser follows orientation.
Uses gamepad axes X/Y (MPU yaw/pitch) mapped to servo pan/tilt.
"""
import math


class HeadTrackMode:
    def __init__(self, mcu, gamepad, mapper):
        self.mcu = mcu
        self.gamepad = gamepad
        self.mapper = mapper
        self.center_yaw = 0.0
        self.center_pitch = 0.0
        self._calibrated = False

    def start(self):
        self.mapper.reset()
        self._calibrated = False
        print("[HeadTrack] Mode active.")
        print("  Point gamepad — laser follows orientation.")
        print("  Press BUTTON 1 (PB0) to calibrate center position.")
        print("  Press BUTTON 12+11+10 to reset yaw (same as gamepad reset combo).")

    def update(self):
        if not self.gamepad or not self.gamepad.connected:
            return

        self.gamepad.update()
        axes = self.gamepad.get_axes()
        buttons = self.gamepad.get_buttons()

        if buttons and buttons[0] and not self._calibrated:
            self.center_yaw = self._map_axis_to_degrees(axes[0])
            self.center_pitch = self._map_axis_to_degrees(axes[1])
            self._calibrated = True
            print(f"[HeadTrack] Calibrated center: yaw={self.center_yaw:.1f} pitch={self.center_pitch:.1f}")

        if len(buttons) >= 12:
            if buttons[9] and buttons[10] and buttons[11]:
                self.center_yaw = self._map_axis_to_degrees(axes[0])
                self.center_pitch = self._map_axis_to_degrees(axes[1])
                self.mapper.reset()
                print("[HeadTrack] Yaw/roll/pitch reset.")

        yaw = self._map_axis_to_degrees(axes[0])
        pitch = self._map_axis_to_degrees(axes[1])

        pan, tilt = self.mapper.mpu_orientation_to_servo(
            yaw, pitch, self.center_yaw, self.center_pitch
        )

        self.mcu.process_command(f"A:{pan:.1f},{tilt:.1f}")

        if len(buttons) > 5 and buttons[5]:
            self.mcu.process_command("L:1")
        elif len(buttons) > 4 and buttons[4]:
            self.mcu.process_command("L:0")

        self.mcu.update()

    def _map_axis_to_degrees(self, axis_val):
        return (axis_val / 255.0) * 360.0 - 180.0

    def get_state(self):
        axes = self.gamepad.get_axes() if self.gamepad and self.gamepad.connected else [127.5] * 8
        yaw = self._map_axis_to_degrees(axes[0])
        pitch = self._map_axis_to_degrees(axes[1])
        return {
            "mode": "HEAD_TRACK",
            "input": f"MPU: yaw={yaw:.1f}° pitch={pitch:.1f}°",
        }

    def stop(self):
        print("[HeadTrack] Stopped.")
