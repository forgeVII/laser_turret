"""
Turret Visualizer — real-time display of turret state.
Shows: top-down pan view, side tilt view, laser dot position, status panel.
Uses matplotlib with animation.
"""
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.animation import FuncAnimation
import math


class TurretVisualizer:
    def __init__(self):
        self.fig = plt.figure(figsize=(14, 7), facecolor="#1a1a2e")
        self.fig.canvas.manager.set_window_title("Laser Turret Simulation")

        self.ax_top = self.fig.add_subplot(121)
        self.ax_top.set_title("TOP VIEW (Pan)", color="white", fontsize=12)
        self.ax_top.set_xlim(-150, 150)
        self.ax_top.set_ylim(-150, 150)
        self.ax_top.set_aspect("equal")
        self.ax_top.set_facecolor("#0f0f23")
        self.ax_top.tick_params(colors="gray")

        self.ax_side = self.fig.add_subplot(222)
        self.ax_side.set_title("SIDE VIEW (Tilt)", color="white", fontsize=12)
        self.ax_side.set_xlim(-150, 150)
        self.ax_side.set_ylim(0, 200)
        self.ax_side.set_aspect("equal")
        self.ax_side.set_facecolor("#0f0f23")
        self.ax_side.tick_params(colors="gray")

        self.ax_status = self.fig.add_subplot(224)
        self.ax_status.set_xlim(0, 10)
        self.ax_status.set_ylim(0, 10)
        self.ax_status.axis("off")
        self.ax_status.set_facecolor("#1a1a2e")

        self._draw_base(self.ax_top)
        self._draw_base_side(self.ax_side)

        self.pan = 90.0
        self.tilt = 90.0
        self.laser_on = False
        self.distance = -1.0
        self.mode_name = "MANUAL"
        self.gamepad_status = "Disconnected"
        self.input_info = ""

        self._laser_line_top, = self.ax_top.plot([], [], color="red", linewidth=2)
        self._laser_dot_top, = self.ax_top.plot([], [], "o", color="red", markersize=8)
        self._turret_body_top = patches.Circle((0, 0), 15, color="#444444", zorder=5)
        self.ax_top.add_patch(self._turret_body_top)

        self._laser_line_side, = self.ax_side.plot([], [], color="red", linewidth=2)
        self._laser_dot_side, = self.ax_side.plot([], [], "o", color="red", markersize=8)
        self._turret_body_side = patches.Rectangle((-10, 0), 20, 15, color="#444444", zorder=5)
        self.ax_side.add_patch(self._turret_body_side)

        self._status_texts = []
        self._anim = None

    def _draw_base(self, ax):
        circle = patches.Circle((0, 0), 120, fill=False, edgecolor="#333355", linewidth=1)
        ax.add_patch(circle)
        for angle in range(0, 360, 30):
            rad = math.radians(angle)
            ax.plot([0, 110 * math.cos(rad)], [0, 110 * math.sin(rad)],
                    color="#222244", linewidth=0.5)
            ax.text(120 * math.cos(rad), 120 * math.sin(rad),
                    f"{angle}°", color="gray", fontsize=7, ha="center", va="center")

    def _draw_base_side(self, ax):
        ax.axhline(y=0, color="#333355", linewidth=1)
        for angle in range(0, 181, 30):
            rad = math.radians(angle)
            x = 100 * math.cos(rad)
            y = 100 * math.sin(rad) + 10
            ax.plot([0, x], [10, y], color="#222244", linewidth=0.5)
            ax.text(x + 5, y + 5, f"{angle}°", color="gray", fontsize=7)

    def update_state(self, pan, tilt, laser_on, distance=-1, mode="MANUAL",
                     gamepad="Disconnected", input_info=""):
        self.pan = pan
        self.tilt = tilt
        self.laser_on = laser_on
        self.distance = distance
        self.mode_name = mode
        self.gamepad_status = gamepad
        self.input_info = input_info

    def _update_frame(self, frame):
        pan_rad = math.radians(self.pan)
        tilt_rad = math.radians(self.tilt)

        laser_len = 120 if self.laser_on else 0
        end_x = laser_len * math.cos(pan_rad)
        end_y = laser_len * math.sin(pan_rad)

        if self.laser_on:
            self._laser_line_top.set_data([0, end_x], [0, end_y])
            self._laser_dot_top.set_data([end_x], [end_y])
        else:
            self._laser_line_top.set_data([], [])
            self._laser_dot_top.set_data([], [])

        barrel_len = 80
        side_end_x = barrel_len * math.cos(tilt_rad)
        side_end_y = barrel_len * math.sin(tilt_rad) + 10

        if self.laser_on:
            self._laser_line_side.set_data([0, side_end_x], [10, side_end_y])
            self._laser_dot_side.set_data([side_end_x], [side_end_y])
        else:
            self._laser_line_side.set_data([], [])
            self._laser_dot_side.set_data([], [])

        self._turret_body_top.set_center((0, 0))

        laser_color = "red" if self.laser_on else "#333333"
        self._laser_line_top.set_color(laser_color)
        self._laser_dot_top.set_color(laser_color)
        self._laser_line_side.set_color(laser_color)
        self._laser_dot_side.set_color(laser_color)

        self.ax_status.clear()
        self.ax_status.set_xlim(0, 10)
        self.ax_status.set_ylim(0, 10)
        self.ax_status.axis("off")
        self.ax_status.set_facecolor("#1a1a2e")

        status_lines = [
            (f"MODE: {self.mode_name}", "#00ff88", 14),
            (f"Pan:  {self.pan:.1f}°", "white", 11),
            (f"Tilt: {self.tilt:.1f}°", "white", 11),
            (f"Laser: {'ON' if self.laser_on else 'OFF'}",
             "red" if self.laser_on else "gray", 11),
        ]
        if self.distance >= 0:
            status_lines.append((f"Dist: {self.distance:.0f} cm", "#ffaa00", 11))
        status_lines.append(("", "white", 6))
        status_lines.append((f"Gamepad: {self.gamepad_status}", "#8888ff", 10))
        if self.input_info:
            status_lines.append((self.input_info, "gray", 9))

        y_pos = 9.0
        for text, color, size in status_lines:
            self.ax_status.text(0.5, y_pos, text, color=color, fontsize=size,
                                fontfamily="monospace", transform=self.ax_status.transAxes)
            y_pos -= 0.12

        return []

    def start(self, update_func=None, interval=50):
        self._anim = FuncAnimation(
            self.fig, self._update_frame,
            interval=interval, blit=False, cache_frame_data=False
        )
        plt.tight_layout()
        plt.show(block=True)

    def is_open(self):
        if self._anim:
            return plt.fignum_exists(self.fig.number)
        return False
