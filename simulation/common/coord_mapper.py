"""
Coordinate Mapper — maps any input space to servo angles (0-180).
Handles range mapping, smoothing, dead zones, and inversion.
"""
import time


class CoordMapper:
    def __init__(self, dead_zone=5.0, smoothing=0.3):
        self.dead_zone = dead_zone
        self.smoothing = smoothing
        self._smooth_pan = 90.0
        self._smooth_tilt = 90.0

    def map_range(self, value, in_min, in_max, out_min, out_max):
        value = max(in_min, min(in_max, value))
        normalized = (value - in_min) / (in_max - in_min)
        return out_min + normalized * (out_max - out_min)

    def apply_dead_zone(self, value, center=127.5):
        if abs(value - center) < self.dead_zone:
            return center
        return value

    def smooth(self, pan, tilt):
        self._smooth_pan += self.smoothing * (pan - self._smooth_pan)
        self._smooth_tilt += self.smoothing * (tilt - self._smooth_tilt)
        return round(self._smooth_pan, 1), round(self._smooth_tilt, 1)

    def reset(self):
        self._smooth_pan = 90.0
        self._smooth_tilt = 90.0

    def gamepad_stick_to_servo(self, stick_x, stick_y, invert_y=True):
        stick_x = self.apply_dead_zone(stick_x)
        stick_y = self.apply_dead_zone(stick_y)
        pan = self.map_range(stick_x, 0, 255, 0, 180)
        if invert_y:
            tilt = self.map_range(stick_y, 0, 255, 180, 0)
        else:
            tilt = self.map_range(stick_y, 0, 255, 0, 180)
        return self.smooth(pan, tilt)

    def mpu_orientation_to_servo(self, yaw, pitch, center_yaw=0, center_pitch=0):
        yaw_offset = yaw - center_yaw
        pitch_offset = pitch - center_pitch
        pan = self.map_range(yaw_offset, -180, 180, 0, 180)
        tilt = self.map_range(pitch_offset, -90, 90, 180, 0)
        pan = max(0, min(180, pan))
        tilt = max(0, min(180, tilt))
        return self.smooth(pan, tilt)

    def hand_position_to_servo(self, hand_x, hand_y, frame_w, frame_h):
        pan = self.map_range(hand_x, 0, frame_w, 0, 180)
        tilt = self.map_range(hand_y, 0, frame_h, 180, 0)
        return self.smooth(pan, tilt)

    def face_position_to_servo(self, face_cx, face_cy, frame_w, frame_h):
        pan = self.map_range(face_cx, 0, frame_w, 0, 180)
        tilt = self.map_range(face_cy, 0, frame_h, 180, 0)
        return self.smooth(pan, tilt)

    def person_position_to_servo(self, person_cx, person_cy, frame_w, frame_h):
        pan = self.map_range(person_cx, 0, frame_w, 0, 180)
        tilt = self.map_range(person_cy, 0, frame_h, 180, 0)
        return self.smooth(pan, tilt)
