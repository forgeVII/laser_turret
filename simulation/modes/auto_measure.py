"""
Auto-Measure Mode — turret sweeps and measures distance via HC-SR04.
Simulates automatic sweep + distance reading.
In real build: HC-SR04 mounted on turret gives actual distance.
"""
import time
import math


class AutoMeasureMode:
    def __init__(self, mcu, gamepad, mapper):
        self.mcu = mcu
        self.gamepad = gamepad
        self.mapper = mapper
        self._sweep_angle = 0.0
        self._sweep_dir = 1
        self._sweep_speed = 1.5
        self._tilt_angle = 90.0
        self._sweep_count = 0
        self._measurements = []
        self._sweep_range = (30, 150)
        self._tilt_fixed = 90.0
        self._mode = "horizontal_sweep"

    def start(self):
        self.mapper.reset()
        self._sweep_angle = self._sweep_range[0]
        self._sweep_dir = 1
        self._measurements = []
        print("[AutoMeasure] Mode active.")
        print("  Turret sweeps horizontally, measures distance at each angle.")
        print("  Simulated objects at various distances.")
        print("  Press BUTTON 1 to switch sweep mode (horizontal/vertical/spiral).")

    def update(self):
        if self.gamepad and self.gamepad.connected:
            self.gamepad.update()
            buttons = self.gamepad.get_buttons()
            if buttons and buttons[0]:
                self._next_sweep_mode()

        self._sweep_angle += self._sweep_dir * self._sweep_speed

        if self._sweep_angle >= self._sweep_range[1]:
            self._sweep_angle = self._sweep_range[1]
            self._sweep_dir = -1
            self._sweep_count += 1
        elif self._sweep_angle <= self._sweep_range[0]:
            self._sweep_angle = self._sweep_range[0]
            self._sweep_dir = 1
            self._sweep_count += 1

        if self._mode == "horizontal_sweep":
            pan = self._sweep_angle
            tilt = self._tilt_fixed
        elif self._mode == "vertical_sweep":
            pan = 90.0
            tilt = self._sweep_angle
        else:
            pan = self._sweep_angle
            tilt = 90.0 + 30.0 * math.sin(math.radians(self._sweep_angle * 3))

        self.mcu.process_command(f"A:{pan:.1f},{tilt:.1f}")
        self.mcu.process_command("L:1")

        sim_dist = self._simulate_distance(pan, tilt)
        self.mcu.hcsr04.set_distance(sim_dist)

        self._measurements.append((round(pan, 1), round(tilt, 1), sim_dist))
        if len(self._measurements) > 200:
            self._measurements = self._measurements[-200:]

        self.mcu.update()

    def _simulate_distance(self, pan, tilt):
        base = 120.0
        obj1_angle = 60.0
        obj2_angle = 110.0
        obj3_angle = 90.0

        dist = base
        for obj_a, obj_d in [(obj1_angle, 45.0), (obj2_angle, 80.0), (obj3_angle, 200.0)]:
            diff = abs(pan - obj_a)
            if diff < 15:
                proximity_factor = 1.0 - (diff / 15.0)
                dist = min(dist, obj_d + (base - obj_d) * (1.0 - proximity_factor))

        noise = (hash(str(pan) + str(tilt)) % 10) / 10.0
        return round(dist + noise, 1)

    def _next_sweep_mode(self):
        modes = ["horizontal_sweep", "vertical_sweep", "spiral"]
        idx = modes.index(self._mode) if self._mode in modes else 0
        self._mode = modes[(idx + 1) % len(modes)]
        self._sweep_dir = 1
        print(f"[AutoMeasure] Sweep mode: {self._mode}")

    def get_state(self):
        latest = self._measurements[-1] if self._measurements else (90, 90, -1)
        return {
            "mode": f"AUTO_{self._mode.upper()}",
            "input": f"Angle: {latest[0]:.1f}° | Dist: {latest[2]:.0f}cm | "
                     f"Sweeps: {self._sweep_count}",
        }

    def stop(self):
        print("[AutoMeasure] Stopped.")
