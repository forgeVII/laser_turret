"""
Virtual MCU — simulates STM32 Blue Pill turret controller.
Mimics serial protocol: "A:x,y\n" for angles, "L:1/0\n" for laser.
Provides virtual servos, laser, and HC-SR04 for simulation.
"""
import time


class VirtualServo:
    def __init__(self, name, min_angle=0, max_angle=180, start_angle=90):
        self.name = name
        self.min_angle = min_angle
        self.max_angle = max_angle
        self.current_angle = start_angle
        self.target_angle = start_angle
        self.move_speed = 3.0  # degrees per update step

    def set_target(self, angle):
        self.target_angle = max(self.min_angle, min(self.max_angle, angle))

    def update(self):
        diff = self.target_angle - self.current_angle
        if abs(diff) < 0.5:
            self.current_angle = self.target_angle
            return
        step = self.move_speed if diff > 0 else -self.move_speed
        if abs(diff) < abs(step):
            self.current_angle = self.target_angle
        else:
            self.current_angle += step

    @property
    def angle(self):
        return round(self.current_angle, 1)


class VirtualLaser:
    def __init__(self):
        self.is_on = False

    def set_state(self, on):
        self.is_on = on


class VirtualHC_SR04:
    def __init__(self):
        self.distance_cm = 100.0  # default simulated distance
        self.max_range_cm = 400.0
        self.no_echo = False

    def set_distance(self, dist_cm):
        self.distance_cm = dist_cm
        self.no_echo = False

    def set_no_echo(self):
        self.no_echo = True
        self.distance_cm = -1

    def read(self):
        if self.no_echo:
            return -1
        return round(self.distance_cm, 1)


class VirtualMCU:
    def __init__(self):
        self.servo_x = VirtualServo("Pan", 0, 180, 90)
        self.servo_y = VirtualServo("Tilt", 0, 180, 90)
        self.laser = VirtualLaser()
        self.hcsr04 = VirtualHC_SR04()
        self._command_buffer = ""

    def process_command(self, cmd_str):
        cmd_str = cmd_str.strip()
        if cmd_str.startswith("A:"):
            try:
                parts = cmd_str[2:].split(",")
                x = float(parts[0])
                y = float(parts[1])
                self.servo_x.set_target(x)
                self.servo_y.set_target(y)
            except (ValueError, IndexError):
                pass
        elif cmd_str.startswith("L:"):
            try:
                state = int(cmd_str[2:])
                self.laser.set_state(state != 0)
            except ValueError:
                pass

    def process_serial_data(self, data):
        self._command_buffer += data
        while "\n" in self._command_buffer:
            line, self._command_buffer = self._command_buffer.split("\n", 1)
            self.process_command(line)

    def update(self):
        self.servo_x.update()
        self.servo_y.update()

    def get_status(self):
        return {
            "pan": self.servo_x.angle,
            "tilt": self.servo_y.angle,
            "laser": self.laser.is_on,
            "distance": self.hcsr04.read(),
        }
