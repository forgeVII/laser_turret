"""
Camera Tracker Mode — simulated camera tracking using mouse position.
In simulation: mouse position = detected hand/face/person position.
In real build: replaced with MediaPipe hand/face/object detection.
Sub-modes: hand, face, object (switch with keys).
"""
import time


class CameraTrackerMode:
    HAND = "hand"
    FACE = "face"
    OBJECT = "object"

    def __init__(self, mcu, gamepad, mapper):
        self.mcu = mcu
        self.gamepad = gamepad
        self.mapper = mapper
        self.sub_mode = self.HAND
        self.frame_w = 640
        self.frame_h = 480
        self._mouse_x = self.frame_w // 2
        self._mouse_y = self.frame_h // 2
        self._tracking = True
        self._sim_distances = {
            self.HAND: 30.0,
            self.FACE: 80.0,
            self.OBJECT: 150.0,
        }
        self._sim_x = self.frame_w // 2
        self._sim_y = self.frame_h // 2
        self._sim_target_x = self.frame_w // 2
        self._sim_target_y = self.frame_h // 2
        self._sim_update_timer = 0
        self._try_real_cv = False
        self._real_tracker = None

    def start(self):
        self.mapper.reset()
        print("[CameraTracker] Mode active (SIMULATION).")
        print("  Sub-modes: [1] Hand  [2] Face  [3] Object")
        print("  In simulation: mouse position = target position.")
        print("  Move mouse to simulate detected hand/face.")
        print("  Right trigger = laser ON, Left trigger = laser OFF.")
        self._try_import_cv()

    def _try_import_cv(self):
        try:
            import cv2
            import mediapipe as mp
            print("[CameraTracker] OpenCV + MediaPipe found.")
            print("  Press 'c' to switch to REAL camera tracking.")
            self._try_real_cv = True
        except ImportError:
            print("[CameraTracker] OpenCV/MediaPipe not installed.")
            print("  Using simulated camera input (mouse position).")
            self._try_real_cv = False

    def update(self):
        self._sim_update_timer += 1
        if self._sim_update_timer % 30 == 0:
            import random
            self._sim_target_x += random.randint(-40, 40)
            self._sim_target_y += random.randint(-30, 30)
            self._sim_target_x = max(50, min(self.frame_w - 50, self._sim_target_x))
            self._sim_target_y = max(50, min(self.frame_h - 50, self._sim_target_y))

        self._sim_x += (self._sim_target_x - self._sim_x) * 0.08
        self._sim_y += (self._sim_target_y - self._sim_y) * 0.08

        if self.sub_mode == self.HAND:
            pan, tilt = self.mapper.hand_position_to_servo(
                self._sim_x, self._sim_y, self.frame_w, self.frame_h
            )
        elif self.sub_mode == self.FACE:
            pan, tilt = self.mapper.face_position_to_servo(
                self._sim_x, self._sim_y, self.frame_w, self.frame_h
            )
        else:
            pan, tilt = self.mapper.person_position_to_servo(
                self._sim_x, self._sim_y, self.frame_w, self.frame_h
            )

        self.mcu.process_command(f"A:{pan:.1f},{tilt:.1f}")

        if self.gamepad and self.gamepad.connected:
            self.gamepad.update()
            buttons = self.gamepad.get_buttons()
            if len(buttons) > 5 and buttons[5]:
                self.mcu.process_command("L:1")
            elif len(buttons) > 4 and buttons[4]:
                self.mcu.process_command("L:0")
        else:
            self.mcu.process_command("L:1")

        dist = self._sim_distances.get(self.sub_mode, 100.0)
        self.mcu.hcsr04.set_distance(dist)

        self.mcu.update()

    def set_sub_mode(self, mode):
        if mode in (self.HAND, self.FACE, self.OBJECT):
            self.sub_mode = mode
            print(f"[CameraTracker] Sub-mode: {mode}")

    def get_state(self):
        return {
            "mode": f"CAM_{self.sub_mode.upper()}",
            "input": f"Target: ({self._sim_x:.0f}, {self._sim_y:.0f}) | "
                     f"Dist: {self._sim_distances[self.sub_mode]:.0f}cm",
        }

    def stop(self):
        print("[CameraTracker] Stopped.")
