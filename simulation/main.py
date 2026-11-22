import pygame
import math
import random
import threading
import time
import os

try:
    import serial
    _serial_ok = True
except ImportError:
    _serial_ok = False

from common import kinematics as kin

# --- real turret geometry (must match firmware, new alignment 2026-11-19) ---
PAN_CENTRE, PAN_MIN, PAN_MAX = 100.0, 50.0, 150.0    # X axis / pan (+/-50)
TILT_CENTRE, TILT_MIN, TILT_MAX = 80.0, 40.0, 140.0  # Y axis / tilt (40..140)
AZ_MAX = 50.0         # max pan direction, deg (matches X envelope)
EL_SCALE = 50.0       # vertical camera scale used for direction mapping
WALL_D = 200.0        # cm, virtual wall used only for the on-screen dot

# --- turret transport: "wifi" (ESP32 bridge) or "serial" (CP2102 fallback) ---
LINK_MODE = "wifi"

# Windows DPI awareness: without this SDL reports 1440x900 on a 2880x1800
# screen and Windows upscales the window, which makes everything look soft.
if os.name == "nt":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

pygame.init()

# The fixed 1300x750 layout is drawn at native desktop pixel scale, so text and
# lines stay crisp at 2880x1800. F11 toggles fullscreen / windowed.
WIDTH, HEIGHT = 1300, 750
_DISPLAY_SIZES = pygame.display.get_desktop_sizes()
DISPLAY_W, DISPLAY_H = _DISPLAY_SIZES[0] if _DISPLAY_SIZES else (WIDTH, HEIGHT)
UI_SCALE = min(DISPLAY_W / WIDTH, DISPLAY_H / HEIGHT)


def sc(v):
    return int(round(v * UI_SCALE))


class SceneSurface(pygame.Surface):
    """Logical-coordinate surface rendered at UI_SCALE resolution."""

    def blit(self, source, dest, *args, **kwargs):
        if isinstance(dest, (tuple, list)):
            dest = (sc(dest[0]), sc(dest[1]))
        else:
            dest = dest.copy()
            dest.x, dest.y = sc(dest.x), sc(dest.y)
        if not getattr(source, "_ui_scaled", False):
            sw, sh = source.get_size()
            if sw <= WIDTH and sh <= HEIGHT:
                source = pygame.transform.smoothscale(source, (sc(sw), sc(sh)))
        return super().blit(source, dest, *args, **kwargs)


class UISurface(pygame.Surface):
    """A surface already rendered at UI_SCALE (blit must not rescale it)."""

    _ui_scaled = True

    # Reports logical sizes so existing centring/layout math keeps working,
    # while the real pixel buffer stays at native resolution for crisp text.
    def get_width(self):
        return int(round(super().get_width() / UI_SCALE))

    def get_height(self):
        return int(round(super().get_height() / UI_SCALE))


def as_ui(src):
    """Wrap a rendered surface so SceneSurface.blit leaves it alone."""
    out = UISurface(src.get_size(), src.get_flags(), src.get_bitsize())
    out.blit(src, (0, 0))
    return out


class ScaledFont:
    """SysFont rendered at UI_SCALE, with logical-size metrics."""

    def __init__(self, name, size, bold=False):
        self._font = pygame.font.SysFont(name, max(8, sc(size)), bold=bold)

    def render(self, text, aa, color):
        return as_ui(self._font.render(text, aa, color))

    def get_height(self):
        return self._font.get_height() / UI_SCALE

    def get_width(self, text):
        return self._font.size(text)[0] / UI_SCALE


_pd = pygame.draw


def drect(surface, color, rect, width=0, *a, **kw):
    if surface is screen:
        if hasattr(rect, "x"):
            rect = pygame.Rect(sc(rect.x), sc(rect.y), sc(rect.w), sc(rect.h))
        else:
            rect = (sc(rect[0]), sc(rect[1]), sc(rect[2]), sc(rect[3]))
        width = sc(width) if width else 0
    return _pd.rect(surface, color, rect, width, *a, **kw)


def dline(surface, color, start, end, width=1, *a, **kw):
    if surface is screen:
        start = (sc(start[0]), sc(start[1]))
        end = (sc(end[0]), sc(end[1]))
        width = sc(width)
    return _pd.line(surface, color, start, end, width, *a, **kw)


def dcircle(surface, color, center, radius, width=0, *a, **kw):
    if surface is screen:
        center = (sc(center[0]), sc(center[1]))
        radius = sc(radius)
        width = sc(width) if width else 0
    return _pd.circle(surface, color, center, radius, width, *a, **kw)


# Windowed at native desktop size by default; F10 = fullscreen, F9 = windowed,
# F11 toggles between them.
WINDOW_W, WINDOW_H = DISPLAY_W, DISPLAY_H
display = pygame.display.set_mode((WINDOW_W, WINDOW_H), pygame.RESIZABLE)
pygame.display.set_caption("LASER TURRET SIMULATOR")
screen = SceneSurface((sc(WIDTH), sc(HEIGHT)))
clock = pygame.time.Clock()
_view = {"scale": 1.0, "x": 0, "y": 0}


def present():
    """Scale the native-resolution scene into the current window."""
    dw, dh = display.get_size()
    scale = min(dw / sc(WIDTH), dh / sc(HEIGHT))
    vw, vh = max(1, int(sc(WIDTH) * scale)), max(1, int(sc(HEIGHT) * scale))
    _view["scale"] = scale
    _view["x"], _view["y"] = (dw - vw) // 2, (dh - vh) // 2
    display.fill((0, 0, 0))
    display.blit(pygame.transform.smoothscale(screen, (vw, vh)),
                 (_view["x"], _view["y"]))
    pygame.display.flip()


def scene_pos(pos):
    """Window pixel -> logical scene pixel (tabs, PIP dragging)."""
    return ((pos[0] - _view["x"]) / (_view["scale"] * UI_SCALE),
            (pos[1] - _view["y"]) / (_view["scale"] * UI_SCALE))


_window_mode = "window"


def set_display_mode(mode):
    """Switch between a native-size resizable window and fullscreen."""
    global display, _window_mode
    if mode == "full":
        display = pygame.display.set_mode((DISPLAY_W, DISPLAY_H), pygame.FULLSCREEN)
        _window_mode = "full"
    else:
        display = pygame.display.set_mode((WINDOW_W, WINDOW_H), pygame.RESIZABLE)
        _window_mode = "window"
    print(f"[Display] {_window_mode} {display.get_size()}")


def toggle_display_mode():
    set_display_mode("window" if _window_mode == "full" else "full")


# Tactical palette, borrowed from TBAS/web/tbas_interface.html: near-black green
# background, phosphor-green readouts, dim grid. LASER stays red for safety.
BG = (8, 11, 8)
PANEL_FILL = (12, 16, 12)
GRID = (26, 42, 26)
TURRET_COL = (26, 64, 44)
TURRET_CEN = (0, 255, 136)
LASER = (255, 40, 40)
TEXT = (200, 220, 200)
GREEN = (0, 255, 136)
GREEN_MID = (0, 187, 102)
GREEN_DIM = (0, 68, 34)
YELLOW = (255, 204, 0)
CYAN = (0, 221, 255)
ORANGE = (255, 140, 0)
RED = (255, 68, 85)
GRAY = (74, 96, 74)
DARK_GRAY = (26, 42, 26)
WALL_BG = (12, 16, 12)
WALL_LINE = (26, 42, 26)
MAGENTA = (255, 0, 200)

FONT_XS = ScaledFont("Consolas", 11)
FONT_S = ScaledFont("Consolas", 13)
FONT = ScaledFont("Consolas", 16)
FONT_B = ScaledFont("Consolas", 20, bold=True)
FONT_BB = ScaledFont("Consolas", 30, bold=True)
FONT_XB = ScaledFont("Consolas", 11, bold=True)

WALL_X, WALL_Y = 330, 60
WALL_W, WALL_H = 940, 529
POSE_X, POSE_Y = 10, 10
POSE_W, POSE_H = 290, 286
HUD_X, HUD_Y = 10, 300
HUD_W = 290

# --- tactical chrome (TBAS-style panels, tabs, scanlines) ---
HEADER_Y, HEADER_H = 8, 44
TAB_W, TAB_H = 100, 24
TAB_X = WALL_X + 250
TAB_Y = HEADER_Y + 10
_scanlines = None


def mode_tab_rects():
    return [pygame.Rect(TAB_X + i * (TAB_W + 6), TAB_Y, TAB_W, TAB_H)
            for i in range(3)]


def draw_frame(surface, rect, accent=None, fill=PANEL_FILL):
    """Square panel with TBAS-style corner ticks."""
    x, y, w, h = rect
    c = accent or GREEN_DIM
    drect(surface, fill, rect)
    drect(surface, c, rect, 1)
    for sx, sy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        px = x if sx == 0 else x + w
        py = y if sy == 0 else y + h
        dx = 8 if sx == 0 else -8
        dy = 8 if sy == 0 else -8
        dline(surface, c, (px, py), (px + dx, py), 1)
        dline(surface, c, (px, py), (px, py + dy), 1)


def draw_scanlines(surface):
    """Subtle CRT overlay, pre-rendered once (single blit per frame)."""
    global _scanlines
    if _scanlines is None:
        _scanlines = UISurface((sc(WIDTH), sc(HEIGHT)), pygame.SRCALPHA)
        _scanlines.fill((0, 0, 0, 0))
        for yy in range(0, sc(HEIGHT), sc(4)):
            dline(_scanlines, (0, 0, 0, 9), (0, yy), (sc(WIDTH), yy))
    surface.blit(_scanlines, (0, 0))


def draw_led(surface, pos, color, radius=4, pulse=1.0):
    """Small status lamp with an optional brightness pulse."""
    c = tuple(int(v * pulse) for v in color)
    dcircle(surface, c, pos, radius)
    dcircle(surface, color, pos, radius + 1, 1)


def draw_bracket(surface, rect, color, arm=14, thick=2):
    """Four tactical corner brackets (lock box / frame accent)."""
    x, y, w, h = rect
    corners = (
        ((x, y), (x + arm, y), (x, y + arm)),
        ((x + w, y), (x + w - arm, y), (x + w, y + arm)),
        ((x, y + h), (x + arm, y + h), (x, y + h - arm)),
        ((x + w, y + h), (x + w - arm, y + h), (x + w, y + h - arm)),
    )
    for (px, py), (ax, ay), (bx, by) in corners:
        dline(surface, color, (bx, by), (px, py), thick)
        dline(surface, color, (px, py), (ax, ay), thick)


def draw_reticle(surface, cx, cy, spread, color, locked=False):
    """Ticked centre reticle used on the wall feed during calibration/lock."""
    dcircle(surface, color, (cx, cy), 12 if locked else 9, 1)
    dline(surface, color, (cx - spread, cy), (cx - 16, cy), 1)
    dline(surface, color, (cx + 16, cy), (cx + spread, cy), 1)
    dline(surface, color, (cx, cy - spread), (cx, cy - 16), 1)
    dline(surface, color, (cx, cy + 16), (cx, cy + spread), 1)
    for d in (-spread + 6, spread - 6):
        dline(surface, color, (cx + d, cy - 4), (cx + d, cy + 4), 1)
        dline(surface, color, (cx - 4, cy + d), (cx + 4, cy + d), 1)
    if locked:
        draw_bracket(surface, (cx - 34, cy - 34, 68, 68), color, arm=10, thick=1)


def draw_header(surface):
    """Top strip: title, clickable mode tabs, live link status."""
    draw_frame(surface, (WALL_X, HEADER_Y, WALL_W, HEADER_H), GREEN_DIM)
    drect(surface, GREEN, (WALL_X, HEADER_Y, 3, HEADER_H))
    title = FONT_B.render("LASER TURRET", True, GREEN)
    surface.blit(title, (WALL_X + 12, HEADER_Y + 4))
    sub = FONT_XS.render("FIRE-CONTROL SIM  //  TACTICAL HUD", True, GRAY)
    surface.blit(sub, (WALL_X + 12, HEADER_Y + 27))

    names = ["1 MANUAL", "2 HAND/FACE", "3 ENEMY"]
    cols = [YELLOW, CYAN, GREEN]
    for i, rect in enumerate(mode_tab_rects()):
        active = current_mode == i + 1
        fill = (0, 34, 20) if active else (10, 14, 10)
        drect(surface, fill, rect)
        drect(surface, cols[i] if active else DARK_GRAY, rect, 1)
        if active:
            drect(surface, cols[i], (rect.x, rect.bottom - 3, rect.w, 3))
        lbl = FONT_XB.render(names[i], True, cols[i] if active else GRAY)
        surface.blit(lbl, (rect.x + (rect.w - lbl.get_width()) // 2,
                           rect.y + (rect.h - lbl.get_height()) // 2))

    sx = WALL_X + WALL_W - 12
    online = link.connected
    link_col = GREEN if online else RED
    lbl = FONT_XS.render("LINK ONLINE" if online else "LINK OFFLINE", True, link_col)
    sx -= lbl.get_width()
    surface.blit(lbl, (sx, HEADER_Y + 10))
    pulse = 0.55 + 0.45 * math.sin(time.time() * (3.0 if online else 8.0))
    draw_led(surface, (sx - 9, HEADER_Y + 17), link_col, 3, pulse)
    host = FONT_XS.render(str(link.host), True, GRAY)
    surface.blit(host, (WALL_X + WALL_W - 12 - host.get_width(), HEADER_Y + 28))


def set_mode(mode):
    """Single mode switch used by keyboard and the clickable HUD tabs."""
    global current_mode, track_source
    current_mode = mode
    if mode == 2 and track_source == "BODY":   # mode 2 only has HAND/FACE
        track_source = "HAND"


def draw_wall_status(surface, x, y, w, h):
    """Segmented telemetry strip at the foot of the wall view."""
    bar_y = y + h - 19
    drect(surface, (6, 10, 6), (x, bar_y, w, 19))
    dline(surface, GREEN_DIM, (x, bar_y), (x + w, bar_y), 1)
    mode_names = ["MANUAL", "HAND/FACE", "ENEMY TRACK"]
    mode_cols = [YELLOW, CYAN, GREEN]
    segs = [
        (mode_names[current_mode - 1], mode_cols[current_mode - 1], 110),
        ("TRACK " + track_source, MAGENTA, 110),
        (f"DIST {active_distance_cm():.0f}cm", CYAN, 100),
        ("LINK OK" if link.connected else "NO LINK",
         GREEN if link.connected else RED, 80),
    ]
    sx = x + 8
    for text, col, width in segs:
        draw_led(surface, (sx + 2, bar_y + 10), col, 2)
        surface.blit(FONT_XS.render(text, True, col), (sx + 9, bar_y + 3))
        sx += width
    hint = FONT_XS.render("M MASK  H DOT  P PIP  R CENTRE  Z ZERO  N DIST",
                          True, GRAY)
    surface.blit(hint, (x + w - hint.get_width() - 8, bar_y + 3))


def project_dot(pan, tilt, x, y, w, h):
    """Real servo angles -> virtual-wall pixel using true turret geometry."""
    e, u = kin.forward(pan, tilt, WALL_D)
    scale = (w * 0.5) / (WALL_D * math.tan(math.radians(AZ_MAX)))
    return (int(x + w * 0.5 + e * scale),
            int(y + h * 0.5 - u * scale))


def hud_mirror(pan, tilt):
    """Mirror the HUD laser point on both axes (screen-only, hardware unchanged)."""
    return 2.0 * PAN_CENTRE - pan, 2.0 * TILT_CENTRE - tilt


# 2026-11-21: mode 3 used to draw the dot unmirrored, which made it travel the
# opposite way to the beam during R centre hold. Display-only; hardware unchanged.
ENEMY_DOT_MIRROR = True


def display_aim(pan, tilt):
    """Servo angles -> wall-view pixel transform for the active camera feed."""
    if current_mode == 3 and not ENEMY_DOT_MIRROR:
        return pan, tilt
    return hud_mirror(pan, tilt)


def direction_from_normalized(nx, ny):
    """Rectilinear-camera normalized (-1..1) point -> beam (az, el) degrees.

    Uses atan so the projected dot lands exactly on the tracked point even
    though the overlay is drawn linearly in pixels.
    """
    az = math.degrees(math.atan(nx * math.tan(math.radians(AZ_MAX))))
    el = math.degrees(math.atan(ny * math.tan(math.radians(EL_SCALE))))
    return az, el


# --- distance-aware aiming (mode 3 + R frame-centre hold in every mode) ---
# The camera cannot measure depth, so the user sets one working distance.
# Single variable value - no slots - because the whole rig moves between sites.
DISTANCE_CM = 90.0

# Measured mount offsets (cm) and effective camera FOV (half-angles, degrees).
# Tune live in the sim: ',' / '.' = HFOV, ';' / ''' = VFOV (1 deg steps).
# Console prints the values; paste them here to make a calibration permanent.
CAM_FWD_CM = 1.0        # camera is forward of (closer to target than) the laser
CAM_DOWN_CM = 1.0       # camera sits below the laser
CAM_EAST_CM = 0.0       # no measured lateral offset
CAM_HFOV_DEG = 34.0   # calibrated at 90 cm: ~68 deg total
CAM_VFOV_DEG = 20.0   # calibrated at 90 cm: ~40 deg total


def active_distance_cm():
    return DISTANCE_CM


def set_active_distance_cm(cm):
    """Set the one working distance (cm, clamped to 20..500)."""
    global DISTANCE_CM
    DISTANCE_CM = max(20.0, min(500.0, cm))
    return DISTANCE_CM


def nudge_distance_cm(delta):
    """Fine-tune the working distance by +/- delta cm ([ / ] keys)."""
    return set_active_distance_cm(DISTANCE_CM + delta)


# N -> type an exact distance (cm). Kept separate from D / [ ] so a measured
# tape value can be entered directly instead of stepping by 10 cm.
distance_entry_active = False
distance_entry_text = ""


def aim_from_camera_point(nx, ny, distance_cm):
    """Camera-normalized point at a known distance -> safe servo angles.

    Converts the image point to an (east, up) target at that distance, adds the
    camera-vs-laser mount offset, then uses the tested exact turret IK. This is
    what stops the beam drifting out of frame away from image centre.
    """
    e_cam = nx * math.tan(math.radians(CAM_HFOV_DEG)) * distance_cm
    u_cam = ny * math.tan(math.radians(CAM_VFOV_DEG)) * distance_cm
    e_wall = e_cam + CAM_EAST_CM
    u_wall = 1.0 + u_cam - CAM_DOWN_CM   # laser tip is 1 cm above tilt base A
    return kin.inverse(e_wall, u_wall, distance_cm + CAM_FWD_CM)


def apply_bias(x, y, az_bias, el_bias):
    """Apply degree-style calibration trims to a solved servo position."""
    az, el = kin.beam_angles(x, y)
    return kin.aim_at_direction(az + az_bias, el + el_bias)


servo_pan = PAN_CENTRE   # real turret X (pan)
servo_tilt = TILT_CENTRE  # real turret Y (tilt)
servo_pan_v = 0.0
servo_tilt_v = 0.0
target_pan = PAN_CENTRE
target_tilt = TILT_CENTRE
aim_pan = PAN_CENTRE
aim_tilt = TILT_CENTRE

# --- motion tuning (2026-11-21: after X servo repair) ---
# Conservative uplift only. Firmware still rate-limits targets to ~100 deg/s,
# so raising the PC side beyond these values would add lag, not real speed.
AIM_SMOOTH = 0.45            # was 0.35: faster tracking, still filtered
STICK_SMOOTH = 0.50          # was 0.40: snappier stick/manual feel
KEY_RATE = 65.0              # was 55: manual KEY units/s
TRACK_TICK_EVERY = 1         # was 2: hand/face/enemy inference every frame
laser_on = False             # MANUAL arm state (Space arms it); safe default OFF
link_engage = False          # single source of truth for HUD + hardware link
show_beam = False            # HUD beam/dot (also shown in STICK mode while disarmed)
current_mode = 1
manual_input = "STICK"

SERVO_MAX_VEL = 280.0        # unchanged: firmware is the real ~100 deg/s limit
SERVO_MAX_ACCEL = 1800.0     # was 1400: quicker ramp, same top speed
SERVO_GAIN = 8.0             # was 6: tighter small-error tracking

# --- cameras ---
camera_ok = False
camera_cap = None
camera_frame = None
camera_raw = None

target_ok = False
target_cap = None
target_frame = None
target_raw = None
available_cameras = []
user_cam_idx = 0
target_cam_idx = 1

# Direct phone-camera stream (IP Webcam MJPEG), no DroidCam client/driver.
# Set live with V, or paste here: http://192.168.4.3:8080/video
TARGET_CAMERA_URL = ""
camera_url_entry_active = False
camera_url_text = ""

setup_active = True
setup_selected = 0

try:
    import cv2
    import numpy as np
    import time as _time

    _last_rescan = 0.0


    def rescan_cameras(force=False):
        global available_cameras, _last_rescan
        now = _time.time()
        if not force and (now - _last_rescan) < 2.0:
            return available_cameras
        _last_rescan = now
        found = []
        for cam_id in range(8):
            cap = cv2.VideoCapture(cam_id)
            if cap.isOpened():
                found.append(cam_id)
                cap.release()
        available_cameras = found
        return found


    def _init_camera_thread():
        global user_cam_idx, camera_cap, camera_ok, available_cameras
        found = rescan_cameras(force=True)
        available_cameras = found
        if not found:
            print("[Camera] No cameras found")
            return
        cap = cv2.VideoCapture(found[0])
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            camera_cap = cap
            camera_ok = True
            user_cam_idx = found[0]
            print(f"[CamA] User/tracker camera = index {user_cam_idx}")
        print(f"[Camera] Available indices: {found}")
        print(f"[Camera] Assign cams in setup screen (TAB) or Y/U after")


    threading.Thread(target=_init_camera_thread, daemon=True).start()
except Exception as e:
    print(f"[Camera] Disabled: {e}")

# --- hand tracking (MediaPipe tasks API, v1.0+) ---
hand_ok = False
hand_detected = False
hand_x = 0.5
hand_y = 0.5
hand_gesture = "OPEN"
hand_pts = []
hand_pts_draw = []
hand_tick = 0

pose_ok = False          # BODY lock (mode 3 wide-target tracking)
pose_lm = None
face_ok = False
face_detected = False
face_x = 0.5
face_y = 0.5
face_nose = (0.5, 0.5)
face_pts = []
face_pts_draw = []
face_tick = 0
head_yaw = 0.0
head_pitch = 0.0
head_roll = 0.0

HEAD_YAW_GAIN = 2.4
HEAD_PITCH_GAIN = 3.0
HEAD_PAN = 90.0
HEAD_TILT = 90.0
HEAD_CENTER_YAW = 0.0
HEAD_CENTER_PITCH = 0.0
HEAD_YAW_FLIP = 1.0
HEAD_PITCH_FLIP = 1.0    # flipped 2026-11-19: head up -> tilt up after re-alignment

# front/front-camera enemy tracking (mode 3)
enemy_detected = False
enemy_x = 0.5
enemy_y = 0.5
enemy_pts = []
enemy_tick = 0
body_confirm = 0   # require 2 consistent BODY frames before arming the laser

# Frame-centre calibration for the enemy camera.
# The phone camera sits ~1 cm BELOW and ~1 cm FORWARD of the laser, so a beam
# sent straight down the camera axis lands slightly HIGH on a near target.
# Bias is in beam-angle degrees, applied at frame centre AND to every lock.
#   + az = aim further right     + el = aim higher
# Tune with R (any mode, laser ON) + held arrow keys, then copy the
# printed values here so they survive a restart.
ENEMY_CENTER_AZ_BIAS = 0.0
ENEMY_CENTER_EL_BIAS = 0.0
# Same frame-centre trim for the tracker camera (modes 1/2 when no target cam).
USER_CENTER_AZ_BIAS = 0.0
USER_CENTER_EL_BIAS = 0.0
ENEMY_X_FLIP = -1.0   # 2026-11-20 live test: mode 3 target->beam was swapped on both axes
ENEMY_Y_FLIP = -1.0   # -1 = image-up -> aim DOWN (camera/mount view is inverted)
enemy_az_bias = ENEMY_CENTER_AZ_BIAS
enemy_el_bias = ENEMY_CENTER_EL_BIAS
user_az_bias = USER_CENTER_AZ_BIAS
user_el_bias = USER_CENTER_EL_BIAS
centre_hold = False       # R: frame-centre hold + laser ON, works in all modes

# R calibration is a FINE trim, not manual flight. Manual KEY speed (now 65
# units/s) let a 1-second hold slam the servo into its end stop. Keep R slow.
R_BIAS_RATE = 8.0         # deg/s while an arrow is held in R
R_BIAS_LIMIT = 10.0       # deg; cannot drive X/Y to the envelope ends


def active_centre_bias():
    """Bias belongs to the camera shown in the wall view, not the mode."""
    if target_ok:
        return enemy_az_bias, enemy_el_bias
    return user_az_bias, user_el_bias


track_source = "HAND"
show_mask = True
show_dot = True              # H toggles the on-screen laser dot (hardware unchanged)
show_pip = True              # P toggles the draggable webcam PIP
PIP_W, PIP_H = 260, 155
pip_rect = pygame.Rect(WALL_X + WALL_W - PIP_W - 8,
                       WALL_Y + WALL_H - PIP_H - 8, PIP_W, PIP_H)
pip_drag = False
pip_drag_off = (0, 0)

# --- turret link (ESP32 SoftAP bridge / CP2102 fallback) ---
# No hotspot, no ARP discovery, no host cache: the bridge is fixed at
# 192.168.4.1:8888 whenever the PC is joined to TURRET_LINK.
from common.turret_link import TurretLink, TURRET_HOST, TURRET_PORT

link = TurretLink(
    mode=LINK_MODE,
    port="COM4",
    baud=115200,
    host=TURRET_HOST,
    tcp_port=TURRET_PORT,
    heartbeat=0.8,
)
arm_last_cmd = None

# --- face recognition (ArcFace embeddings) ---
face_recog = None
recog_ready = False
recog_user = None
recog_threshold = 0.30
recog_conf = 0.0
recog_last_embed = None
recog_next_time = 0.0
recog_cand = None
recog_cand_hits = 0

try:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision
    import os

    base_dir = os.path.dirname(os.path.abspath(__file__))
    hand_model = os.path.join(base_dir, "hand_landmarker.task")
    face_model = os.path.join(base_dir, "face_landmarker.task")
    pose_model = os.path.join(base_dir, "pose_landmarker_lite.task")
    hand_opts = vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=hand_model),
        running_mode=vision.RunningMode.IMAGE,
        num_hands=4,          # enemy mode: pick largest hand
        min_hand_detection_confidence=0.4,
        min_hand_presence_confidence=0.4,
        min_tracking_confidence=0.4,
    )
    face_opts = vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=face_model),
        running_mode=vision.RunningMode.IMAGE,
        num_faces=4,          # enemy mode: pick largest head
        min_face_detection_confidence=0.4,
        min_face_presence_confidence=0.4,
        min_tracking_confidence=0.4,
        output_facial_transformation_matrixes=True,
    )
    # BODY is optional: a missing pose model must not disable hand/face.
    pose_opts = None
    if os.path.exists(pose_model):
        pose_opts = vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=pose_model),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=4,          # mode 3: pick largest human body
            # Lite model false-positived on random shapes at 0.3. Be strict;
            # process_enemy() also checks torso visibility + body proportions.
            min_pose_detection_confidence=0.65,
            min_pose_presence_confidence=0.65,
            min_tracking_confidence=0.65,
        )
    else:
        print("[Track] BODY disabled: pose_landmarker_lite.task missing")
    hand_lm = None
    face_lm = None
    pose_lm = None
    hand_ok = True
    face_ok = True
    pose_ok = pose_opts is not None
    mp_image = mp.Image
    hand_mp = mp


    def _load_models():
        global hand_lm, face_lm, pose_lm
        _h = vision.HandLandmarker.create_from_options(hand_opts)
        _f = vision.FaceLandmarker.create_from_options(face_opts)
        hand_lm = _h
        face_lm = _f
        if pose_opts is not None:
            try:
                pose_lm = vision.PoseLandmarker.create_from_options(pose_opts)
            except Exception as e:
                print(f"[Track] BODY model failed to load: {e}")
        loaded = "hand + face" + (" + body" if pose_lm is not None else "")
        print(f"[Track] MediaPipe tasks API ready ({loaded})")


    threading.Thread(target=_load_models, daemon=True).start()
except FileNotFoundError:
    print("[Track] A .task model file was not found")
except Exception as e:
    print(f"[Track] Disabled: {e}")

try:
    import os as _os
    from common.face_ai import FaceRecognizer
    _bd = _os.path.dirname(_os.path.abspath(__file__))
    face_recog = FaceRecognizer(
        _os.path.join(_bd, "arcface.onnx"),
        _os.path.join(_bd, "users.json"),
    )
    threading.Thread(target=_init_face_recog, daemon=True).start()
except Exception as e:
    print(f"[FaceAI] Disabled: {e}")


def _init_face_recog():
    global face_recog, recog_ready
    try:
        if face_recog is not None and face_recog.load_model():
            recog_ready = True
            print(f"[FaceAI] ArcFace ready ({len(face_recog.users)} users enrolled)")
    except Exception as e:
        print(f"[FaceAI] init failed: {e}")

gamepad_connected = False
joy = None
gamepad_axes = [127.5] * 8
joystick_list = []


def _grab_joystick():
    global joy, gamepad_connected, joystick_list
    try:
        pygame.joystick.init()
        count = pygame.joystick.get_count()
        joystick_list = []
        for i in range(count):
            j = pygame.joystick.Joystick(i)
            j.init()
            joystick_list.append(j)
        if joystick_list:
            prefer = None
            for j in joystick_list:
                name = j.get_name().lower()
                if "vjoy" not in name and "virtual" not in name:
                    prefer = j
                    break
            if prefer is None:
                prefer = joystick_list[0]
            joy = prefer
            gamepad_connected = True
            print(f"[Gamepad] Connected: {joy.get_name()} (idx {joystick_list.index(joy)})")
        else:
            joy = None
            gamepad_connected = False
    except Exception as e:
        joy = None
        gamepad_connected = False
        print(f"[Gamepad] Error: {e}")


def _cycle_joystick():
    global joy, gamepad_connected, joystick_list
    if len(joystick_list) <= 1:
        print("[Gamepad] Only one joystick available")
        return
    cur = joystick_list.index(joy) if joy in joystick_list else -1
    nxt = joystick_list[(cur + 1) % len(joystick_list)]
    joy = nxt
    gamepad_connected = True
    print(f"[Gamepad] Switched to: {joy.get_name()} (idx {joystick_list.index(joy)})")

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
]
FINGER_TIPS = [4, 8, 12, 16, 20]
FINGER_PIPS = [3, 6, 10, 14, 18]

FACE_CONNECTIONS = [
    (10, 338), (338, 297), (297, 332), (332, 284), (284, 251), (251, 389),
    (389, 356), (356, 454), (454, 323), (323, 361), (361, 288), (288, 397),
    (397, 365), (365, 379), (379, 378), (378, 400), (400, 377), (377, 152),
    (152, 148), (148, 176), (176, 149), (149, 150), (150, 136), (136, 172),
    (172, 58), (58, 132), (132, 93), (93, 234), (234, 127), (127, 162),
    (162, 21), (21, 54), (54, 103), (103, 67), (67, 109),
    (33, 7), (7, 163), (163, 144), (144, 145), (145, 153), (153, 154),
    (154, 155), (155, 133), (133, 173), (173, 157), (157, 158), (158, 159),
    (159, 160), (160, 161), (161, 246), (246, 33),
    (263, 249), (249, 390), (390, 373), (373, 374), (374, 380), (380, 381),
    (381, 382), (382, 362), (362, 398), (398, 384), (384, 385), (385, 386),
    (386, 387), (387, 388), (388, 466), (466, 263),
]
FACE_NOSE_TIP = 1
FACE_NOSE_BRIDGE = 168

# MediaPipe Pose: shoulders + hips make a wide, forgiving lock point, so mode 3
# does not need face/hand-level precision to hit a person.
BODY_TORSO = (11, 12, 23, 24)
# Reject random objects: need a mostly-visible, plausibly-shaped person.
BODY_MIN_VISIBLE = 10      # of 33 pose landmarks above 0.5 visibility
BODY_TORSO_MIN_VISIBLE = 3 # of shoulders(11,12)+hips(23,24)
BODY_MIN_AREA = 0.04       # >= 4% of the frame
BODY_MIN_W = 0.06
BODY_MIN_H = 0.08
BODY_MAX_ASPECT = 3.0      # reject very flat / very thin detections
BODY_CONNECTIONS = [
    (0, 11), (0, 12), (11, 12),
    (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (24, 26), (26, 28),
]

fire_flash_timer = 0
hit_ring = 0.0
hit_x = 0
hit_y = 0


def capture_camera():
    global camera_raw
    if not camera_ok or camera_cap is None:
        return None
    ret, frame = camera_cap.read()
    if not ret or frame is None:
        return camera_raw
    camera_raw = frame
    return camera_raw


def capture_target():
    global target_raw
    if not target_ok or target_cap is None:
        return None
    ret, frame = target_cap.read()
    if not ret or frame is None:
        return target_raw
    target_raw = frame
    return target_raw


def draw_tracker_pip(surface):
    """Draggable webcam window. P hides/shows it; drag its title to move."""
    x, y, w, h = pip_rect.x, pip_rect.y, pip_rect.w, pip_rect.h
    draw_frame(surface, pip_rect, CYAN if pip_drag else GREEN_DIM,
               fill=(8, 12, 8))
    cap_h = 16
    drect(surface, (8, 20, 12), (x + 1, y + 1, w - 2, cap_h))
    draw_led(surface, (x + 10, y + 9), GREEN, 3,
             0.6 + 0.4 * math.sin(time.time() * 4.0))
    lbl = FONT_XS.render("TRACKER / USER CAM", True,
                         CYAN if pip_drag else GREEN_MID)
    surface.blit(lbl, (x + 18, y + 3))
    drag = FONT_XS.render("DRAG", True, GRAY)
    surface.blit(drag, (x + w - drag.get_width() - 6, y + 3))
    if camera_raw is None:
        return
    try:
        frame = cv2.cvtColor(camera_raw, cv2.COLOR_BGR2RGB)
        frame = np.fliplr(frame)
        fh, fw = frame.shape[:2]
        view_w, view_h = sc(w - 2), sc(h - cap_h - 1)
        target_aspect = view_w / view_h
        src_aspect = fw / fh
        if src_aspect > target_aspect:
            new_w = int(fh * target_aspect)
            x0 = (fw - new_w) // 2
            frame = frame[:, x0:x0 + new_w]
        else:
            new_h = int(fw / target_aspect)
            y0 = (fh - new_h) // 2
            frame = frame[y0:y0 + new_h, :]
        frame = cv2.resize(frame, (view_w, view_h))
        surf = as_ui(pygame.image.frombuffer(frame.tobytes(), (view_w, view_h), "RGB"))
        surface.blit(surf, (x + 1, y + cap_h))
    except Exception:
        pass


def get_camera_surface(w, h):
    global camera_frame, camera_raw
    if target_ok and target_cap is not None:
        raw = target_raw
        flipped = False
    else:
        raw = camera_raw
        flipped = True
    if raw is None or not camera_ok:
        return camera_frame
    try:
        frame = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
        if flipped:
            frame = np.fliplr(frame)
        fh, fw = frame.shape[:2]
        target_aspect = w / h
        src_aspect = fw / fh
        if src_aspect > target_aspect:
            new_w = int(fh * target_aspect)
            x0 = (fw - new_w) // 2
            frame = frame[:, x0:x0 + new_w]
        else:
            new_h = int(fw / target_aspect)
            y0 = (fh - new_h) // 2
            frame = frame[y0:y0 + new_h, :]
        rw, rh = sc(w), sc(h)
        frame = cv2.resize(frame, (rw, rh))
        surf = as_ui(pygame.image.frombuffer(frame.tobytes(), (rw, rh), "RGB"))
        camera_frame = surf
        return surf
    except Exception:
        return camera_frame


def process_hands():
    global hand_detected, hand_x, hand_y, hand_gesture, hand_pts, hand_pts_draw
    if not hand_ok or hand_lm is None or camera_raw is None:
        hand_detected = False
        hand_pts = []
        hand_pts_draw = []
        return
    try:
        rgb = cv2.cvtColor(camera_raw, cv2.COLOR_BGR2RGB)
        img = mp_image(image_format=hand_mp.ImageFormat.SRGB, data=rgb)
        result = hand_lm.detect(img)
        if result.hand_landmarks:
            lm = result.hand_landmarks[0]
            pts = [(p.x, p.y) for p in lm]
            hand_pts = pts
            hand_x = (pts[0][0] + pts[9][0]) * 0.5
            hand_y = (pts[0][1] + pts[9][1]) * 0.5
            open_fingers = sum(1 for t, p in zip(FINGER_TIPS, FINGER_PIPS) if pts[t][1] < pts[p][1])
            if open_fingers <= 1:
                hand_gesture = "FIST"
            elif open_fingers >= 4:
                hand_gesture = "OPEN"
            else:
                hand_gesture = "PARTIAL"
            hand_detected = True
        else:
            hand_detected = False
            hand_pts = []
            hand_pts_draw = []
    except Exception:
        hand_detected = False
        hand_pts = []
        hand_pts_draw = []


def process_faces():
    global face_detected, face_x, face_y, face_nose, face_pts, face_pts_draw
    global head_yaw, head_pitch, head_roll
    if not face_ok or face_lm is None or camera_raw is None:
        face_detected = False
        face_pts = []
        face_pts_draw = []
        return
    try:
        rgb = cv2.cvtColor(camera_raw, cv2.COLOR_BGR2RGB)
        img = mp_image(image_format=hand_mp.ImageFormat.SRGB, data=rgb)
        result = face_lm.detect(img)
        if result.face_landmarks:
            lm = result.face_landmarks[0]
            pts = [(p.x, p.y) for p in lm]
            face_pts = pts
            nose = pts[FACE_NOSE_TIP]
            face_nose = nose
            face_x = nose[0] if nose[0] > 0.001 else sum(p[0] for p in pts) / 468.0
            face_y = nose[1]
            face_detected = True
            if getattr(result, "facial_transformation_matrixes", None):
                M = result.facial_transformation_matrixes[0]
                sy = math.sqrt(M[0][0] ** 2 + M[1][0] ** 2)
                if sy > 1e-6:
                    pitch = math.degrees(math.atan2(M[2][1], M[2][2]))
                    yaw = math.degrees(math.atan2(-M[2][0], sy))
                    roll = math.degrees(math.atan2(M[1][0], M[0][0]))
                else:
                    pitch = math.degrees(math.atan2(-M[1][2], M[1][1]))
                    yaw = math.degrees(math.atan2(-M[2][0], sy))
                    roll = 0.0
                head_yaw = yaw
                head_pitch = pitch
                head_roll = roll
        else:
            face_detected = False
            face_pts = []
            face_pts_draw = []
    except Exception:
        face_detected = False
        face_pts = []
        face_pts_draw = []
    _maybe_recognize()


def process_enemy():
    """Front/target camera: lock largest HAND, HEAD or BODY (T cycles)."""
    global enemy_detected, enemy_x, enemy_y, enemy_pts, body_confirm
    if target_raw is None or not (face_ok or hand_ok or pose_ok):
        enemy_detected = False
        enemy_pts = []
        return
    try:
        rgb = cv2.cvtColor(target_raw, cv2.COLOR_BGR2RGB)
        img = mp_image(image_format=hand_mp.ImageFormat.SRGB, data=rgb)
        best = None  # (bbox area, u, v, landmarks)
        confirmed = True   # BODY needs 2 agreeing frames; HAND/FACE do not
        if track_source == "FACE" and face_ok:
            res = face_lm.detect(img)
            for lm in (res.face_landmarks or []):
                pts = [(p.x, p.y) for p in lm]
                area = ((max(p[0] for p in pts) - min(p[0] for p in pts)) *
                        (max(p[1] for p in pts) - min(p[1] for p in pts)))
                nose = pts[FACE_NOSE_TIP]
                if best is None or area > best[0]:
                    best = (area, nose[0], nose[1], pts)
        elif track_source == "BODY" and pose_ok and pose_lm is not None:
            res = pose_lm.detect(img)
            for lm in (res.pose_landmarks or []):
                vis = [getattr(p, "visibility", 0.0) for p in lm]
                visible = [(p.x, p.y) for p, v in zip(lm, vis) if v >= 0.5]
                if len(visible) < BODY_MIN_VISIBLE:
                    continue
                torso_vis = [vis[i] for i in BODY_TORSO]
                if sum(1 for v in torso_vis if v >= 0.5) < BODY_TORSO_MIN_VISIBLE:
                    continue
                bw = max(p[0] for p in visible) - min(p[0] for p in visible)
                bh = max(p[1] for p in visible) - min(p[1] for p in visible)
                if bw < BODY_MIN_W or bh < BODY_MIN_H:
                    continue
                if bw / bh > BODY_MAX_ASPECT or bh / bw > BODY_MAX_ASPECT:
                    continue
                pts = [(p.x, p.y) for p in lm]
                # Torso centre (shoulders + hips) = wide, forgiving target.
                u = sum(pts[i][0] for i in BODY_TORSO) / len(BODY_TORSO)
                v = sum(pts[i][1] for i in BODY_TORSO) / len(BODY_TORSO)
                area = bw * bh
                if area >= BODY_MIN_AREA and (best is None or area > best[0]):
                    best = (area, u, v, pts)
            if best:
                confirmed = body_confirm >= 1
                body_confirm = 2 if confirmed else 1
            else:
                body_confirm = max(0, body_confirm - 1)
        else:
            body_confirm = 0
        if track_source == "HAND" and hand_ok:
            res = hand_lm.detect(img)
            for lm in (res.hand_landmarks or []):
                pts = [(p.x, p.y) for p in lm]
                area = ((max(p[0] for p in pts) - min(p[0] for p in pts)) *
                        (max(p[1] for p in pts) - min(p[1] for p in pts)))
                u = (pts[0][0] + pts[9][0]) * 0.5
                v = (pts[0][1] + pts[9][1]) * 0.5
                if best is None or area > best[0]:
                    best = (area, u, v, pts)
        if best and confirmed:
            enemy_x, enemy_y, enemy_pts = best[1], best[2], best[3]
            enemy_detected = True
        else:
            enemy_detected = False
            enemy_pts = []
    except Exception:
        enemy_detected = False
        enemy_pts = []


def _maybe_recognize():
    global recog_user, recog_conf, recog_last_embed, recog_next_time
    global recog_cand, recog_cand_hits
    if face_recog is None or not recog_ready or face_recog.sess is None:
        return
    if not face_detected or not face_pts or camera_raw is None:
        if recog_cand_hits > 0:
            recog_cand_hits -= 1
            if recog_cand_hits == 0:
                recog_cand = None
                recog_user = None
                recog_conf = 0.0
        return
    now = time.time()
    if now < recog_next_time:
        return
    recog_next_time = now + 0.25
    try:
        h, w = camera_raw.shape[:2]
        xs = [p[0] * w for p in face_pts]
        ys = [p[1] * h for p in face_pts]
        x0, x1 = int(min(xs)), int(max(xs))
        y0, y1 = int(min(ys)), int(max(ys))
        mw, mh = (x1 - x0) * 0.4, (y1 - y0) * 0.4
        x0 = max(0, int(x0 - mw)); x1 = min(w, int(x1 + mw))
        y0 = max(0, int(y0 - mh)); y1 = min(h, int(y1 + mh))
        if (x1 - x0) < 24 or (y1 - y0) < 24:
            return
        emb = face_recog.embed(camera_raw[y0:y1, x0:x1])
        if emb is None:
            return
        recog_last_embed = emb
        name, sim = face_recog.match(emb, threshold=recog_threshold)
        if name is not None:
            if name == recog_cand:
                recog_cand_hits += 1
            else:
                recog_cand = name
                recog_cand_hits = 1
            if recog_cand_hits >= 2:
                recog_user = recog_cand
                recog_conf = sim
        else:
            recog_cand_hits = 0
            recog_cand = None
    except Exception:
        pass


def enroll_face():
    global recog_user
    if face_recog is None or not recog_ready:
        print("[FaceAI] model not ready yet")
        return
    if recog_last_embed is None:
        print("[FaceAI] no face to enroll — hold still in view")
        return
    n = len(face_recog.users) + 1
    name = "PLAYER%d" % n
    while name in face_recog.users:
        n += 1
        name = "PLAYER%d" % n
    face_recog.enroll(name, recog_last_embed)
    recog_user = name
    print(f"[FaceAI] enrolled '{name}' — press E a few times for more samples")


def draw_setup_screen(surface):
    overlay = UISurface((sc(WIDTH), sc(HEIGHT)), pygame.SRCALPHA)
    overlay.fill((4, 8, 4, 225))
    surface.blit(overlay, (0, 0))

    title = FONT_BB.render("CAMERA SETUP", True, GREEN)
    surface.blit(title, (WIDTH // 2 - title.get_width() // 2, 40))
    dline(surface, GREEN_MID,
                     (WIDTH // 2 - title.get_width() // 2, 76),
                     (WIDTH // 2 + title.get_width() // 2, 76), 2)
    info = FONT_S.render("Assign which camera feeds which screen. Press 0-8 to pick a camera for the selected slot.",
                         True, TEXT)
    surface.blit(info, (WIDTH // 2 - info.get_width() // 2, 80))
    info2 = FONT_S.render("TAB switch slot   |   ENTER done   |   ESC quit", True, GRAY)
    surface.blit(info2, (WIDTH // 2 - info2.get_width() // 2, 100))
    info3 = FONT_XS.render("In the sim press V to use a direct phone stream URL (no DroidCam).",
                           True, CYAN)
    surface.blit(info3, (WIDTH // 2 - info3.get_width() // 2, 124))

    slots = [
        ("TRACKER  (your face / hand)", camera_raw, user_cam_idx, 0),
        ("TARGET WALL  (the wall view)", target_raw, target_cam_idx, 1),
    ]
    box_w, box_h = 520, 330
    gap = 40
    total_w = box_w * 2 + gap
    x0 = (WIDTH - total_w) // 2
    y0 = 140
    for i, (name, raw, idx, slot) in enumerate(slots):
        bx = x0 + i * (box_w + gap)
        border = GREEN if setup_selected == slot else GREEN_DIM
        draw_frame(surface, (bx, y0, box_w, box_h), border, PANEL_FILL)
        lbl = FONT_B.render(name, True, GREEN if setup_selected == slot else TEXT)
        surface.blit(lbl, (bx + 15, y0 + 10))
        tag = "ASSIGNED" if (slot == 0 and camera_ok) or (slot == 1 and target_ok) else "NONE"
        tag_col = GREEN if tag == "ASSIGNED" else RED
        tgl = FONT_S.render(f"cam index {idx}  [{tag}]", True, tag_col)
        surface.blit(tgl, (bx + 15, y0 + 40))
        if raw is not None and ((slot == 0 and camera_ok) or (slot == 1 and target_ok)):
            try:
                frame = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
                fh, fw = frame.shape[:2]
                view_w, view_h = box_w - 30, box_h - 80
                target_aspect = view_w / view_h
                src_aspect = fw / fh
                if src_aspect > target_aspect:
                    new_w = int(fh * target_aspect)
                    xc = (fw - new_w) // 2
                    frame = frame[:, xc:xc + new_w]
                else:
                    new_h = int(fw / target_aspect)
                    yc = (fh - new_h) // 2
                    frame = frame[yc:yc + new_h, :]
                rw, rh = sc(view_w), sc(view_h)
                frame = cv2.resize(frame, (rw, rh))
                surf = as_ui(pygame.image.frombuffer(frame.tobytes(), (rw, rh), "RGB"))
                surface.blit(surf, (bx + 15, y0 + 65))
                drect(surface, border, (bx + 15, y0 + 65, view_w, view_h), 1)
            except Exception:
                pass
        else:
            nolbl = FONT_S.render("NO CAMERA", True, GRAY)
            surface.blit(nolbl, (bx + box_w // 2 - nolbl.get_width() // 2, y0 + box_h // 2))

    avail = FONT_S.render("Available: " + ", ".join(str(c) for c in available_cameras), True, CYAN)
    surface.blit(avail, (WIDTH // 2 - avail.get_width() // 2, y0 + box_h + 20))


def recenter_head():
    global HEAD_CENTER_YAW, HEAD_CENTER_PITCH
    HEAD_CENTER_YAW = head_yaw
    HEAD_CENTER_PITCH = head_pitch


def cycle_target_camera():
    global target_ok, target_cap, target_raw, target_cam_idx
    if available_cameras:
        assign_target_camera(available_cameras[(available_cameras.index(target_cam_idx) + 1) % len(available_cameras)] if target_cam_idx in available_cameras else available_cameras[0])


def cycle_user_camera():
    global camera_ok, camera_cap, camera_raw, user_cam_idx
    if available_cameras:
        assign_user_camera(available_cameras[(available_cameras.index(user_cam_idx) + 1) % len(available_cameras)] if user_cam_idx in available_cameras else available_cameras[0])


def assign_target_camera(src):
    """Assign a local camera index or a direct HTTP/MJPEG URL."""
    global target_ok, target_cap, target_raw, target_cam_idx, TARGET_CAMERA_URL
    is_url = isinstance(src, str) and src.strip().lower().startswith(("http://", "https://"))
    if is_url:
        src = src.strip()
    else:
        if src not in available_cameras:
            rescan_cameras()
            if src not in available_cameras:
                probe = cv2.VideoCapture(src)
                opened = probe.isOpened()
                probe.release()
                if not opened:
                    return False
    if target_cap is not None:
        target_cap.release()
        target_cap = None
        target_ok = False
    cap = cv2.VideoCapture(src)
    if cap.isOpened():
        if not is_url:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        target_cap = cap
        target_ok = True
        target_cam_idx = src
        TARGET_CAMERA_URL = src if is_url else ""
        target_raw = None
        label = f"URL {src}" if is_url else f"index {src}"
        print(f"[CamB] Target camera = {label}")
        return True
    cap.release()
    return False


def assign_user_camera(idx):
    global camera_ok, camera_cap, camera_raw, user_cam_idx
    if idx not in available_cameras:
        rescan_cameras()
        if idx not in available_cameras:
            probe = cv2.VideoCapture(idx)
            opened = probe.isOpened()
            probe.release()
            if not opened:
                return False
    if camera_cap is not None:
        camera_cap.release()
        camera_cap = None
        camera_ok = False
    cap = cv2.VideoCapture(idx)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        camera_cap = cap
        camera_ok = True
        user_cam_idx = idx
        camera_raw = None
        print(f"[CamA] User/tracker camera = index {idx}")
        return True
    cap.release()
    return False


def draw_gimbal_pose(surface, x, y, w, h):
    """Live 2D gimbal pose scope: X/Y servo position inside the safe envelope.

    Replaces the old bearing dial + elevation needle boxes. Display only: it
    reads servo_pan/servo_tilt and never writes aiming or link state.
    """
    draw_frame(surface, (x, y, w, h), GREEN_DIM)
    drect(surface, (10, 22, 14), (x + 1, y + 1, w - 2, 22))
    dline(surface, GREEN_DIM, (x + 1, y + 23), (x + w - 2, y + 23), 1)
    surface.blit(FONT_XB.render("GIMBAL POSE", True, GREEN), (x + 8, y + 5))
    tag = FONT_XS.render("X / Y ENVELOPE", True, GRAY)
    surface.blit(tag, (x + w - tag.get_width() - 8, y + 6))

    # Scope uses the WALL CAMERA aspect ratio (WIDTH x HEIGHT, not square), so
    # its dot sits at the same relative spot as the dot on the wall feed.
    sw = w - 24
    sh = int(round(sw * WALL_H / WALL_W))
    sx, sy = x + (w - sw) // 2, y + 30
    drect(surface, (8, 12, 9), (sx, sy, sw, sh))
    drect(surface, GREEN_DIM, (sx, sy, sw, sh), 1)
    cx, cy = sx + sw // 2, sy + sh // 2
    dline(surface, DARK_GRAY, (cx, sy + 1), (cx, sy + sh - 2), 1)
    dline(surface, DARK_GRAY, (sx + 1, cy), (sx + sw - 2, cy), 1)
    for i in range(1, 4):
        ox, oy = sx + sw * i // 4, sy + sh * i // 4
        dline(surface, GRID, (ox, cy - 5), (ox, cy + 5), 1)
        dline(surface, GRID, (cx - 5, oy), (cx + 5, oy), 1)
    dcircle(surface, GREEN_MID, (cx, cy), 4, 1)          # centre = X100 Y80
    draw_bracket(surface, (sx, sy, sw, sh), GREEN_DIM, arm=12, thick=1)

    # Same transform as the wall dot: display_aim (mirror) -> project_dot, then
    # normalise onto the wall rect. Never raw servo values here: that was the
    # left/right reversal against the wall view.
    mx, my = display_aim(servo_pan, servo_tilt)
    wx, wy = project_dot(mx, my, WALL_X, WALL_Y, WALL_W, WALL_H)
    dnx = max(0.0, min(1.0, (wx - WALL_X) / WALL_W))
    dny = max(0.0, min(1.0, (wy - WALL_Y) / WALL_H))
    px = sx + 8 + int(dnx * (sw - 16))
    py = sy + 8 + int(dny * (sh - 16))
    dline(surface, GREEN_DIM, (cx, cy), (px, py), 1)
    dcircle(surface, LASER if link_engage else CYAN, (px, py), 5)
    dcircle(surface, (255, 255, 255), (px, py), 2)

    # X / Y readouts under the scope (values only; sliders live in the HUD card).
    ry = sy + sh + 8
    for label, value in (("X / PAN", servo_pan), ("Y / TILT", servo_tilt)):
        surface.blit(FONT_XS.render(label, True, GRAY), (x + 16, ry))
        vt = FONT_B.render(f"{value:05.1f}", True, CYAN)
        surface.blit(vt, (x + w - 16 - vt.get_width(), ry - 3))
        ry += 22


def draw_target_wall(surface, x, y, w, h):
    cam_surf = get_camera_surface(w, h)
    if cam_surf is not None:
        surface.blit(cam_surf, (x, y))
        drect(surface, GREEN_DIM, (x, y, w, h), 2)
    else:
        drect(surface, WALL_BG, (x, y, w, h))
        drect(surface, GREEN_DIM, (x, y, w, h), 1)
        for gx in range(0, w, 30):
            dline(surface, WALL_LINE, (x + gx, y), (x + gx, y + h), 1)
        for gy in range(0, h, 30):
            dline(surface, WALL_LINE, (x, y + gy), (x + w, y + gy), 1)
    draw_bracket(surface, (x, y, w, h), GREEN_MID, arm=22, thick=2)

    strip = pygame.Surface((210, 16), pygame.SRCALPHA)
    strip.fill((8, 12, 8, 180))
    surface.blit(strip, (x + 2, y + 2))
    src_tag = (f"IP:{target_cam_idx}" if isinstance(target_cam_idx, str) else f"CAM{target_cam_idx}") if target_ok else "SELF"
    lbl = FONT_XB.render("WALL FEED // " + src_tag, True, GREEN)
    surface.blit(lbl, (x + 8, y + 4))

    wall_feed = target_raw if (target_ok and target_raw is not None) else camera_raw
    if wall_feed is not None and (centre_hold or (current_mode == 3 and target_ok)):
        # Reticle = active wall camera frame centre. Put a mark there in the
        # real scene, press R, then hold arrows until the dot covers it.
        cx, cy = x + w // 2, y + h // 2
        draw_reticle(surface, cx, cy, 28, CYAN, locked=centre_hold)
    if current_mode == 3 and enemy_detected and wall_feed is not None:
        tx = x + int(enemy_x * w)
        ty = y + int(enemy_y * h)
        draw_bracket(surface, (tx - 28, ty - 28, 56, 56), MAGENTA, arm=12, thick=2)
        dline(surface, MAGENTA, (tx - 8, ty), (tx + 8, ty), 1)
        dline(surface, MAGENTA, (tx, ty - 8), (tx, ty + 8), 1)

    if show_mask:
        cam_feed = target_raw if (target_ok and target_raw is not None) else camera_raw
        if current_mode == 3 and cam_feed is not None and enemy_pts:
            # front camera is not mirrored -> draw landmarks at raw x
            pts_screen = [(x + int(px * w), y + int(py * h)) for px, py in enemy_pts]
            if track_source == "BODY":
                conns, tip = BODY_CONNECTIONS, None
            elif track_source == "FACE":
                conns, tip = FACE_CONNECTIONS, FACE_NOSE_TIP
            else:
                conns, tip = HAND_CONNECTIONS, 9
            for i, j in conns:
                dline(surface, (0, 255, 255), pts_screen[i], pts_screen[j], 1)
            if tip is not None:
                dcircle(surface, MAGENTA, pts_screen[tip], 7)
                dcircle(surface, MAGENTA, pts_screen[tip], 11, 2)
            else:
                tx = x + int(enemy_x * w)
                ty = y + int(enemy_y * h)
                dcircle(surface, MAGENTA, (tx, ty), 12)
                dcircle(surface, MAGENTA, (tx, ty), 18, 2)
        elif current_mode == 2 and track_source == "HAND" and cam_feed is not None and hand_pts:
            fh, fw = cam_feed.shape[:2]
            pts_screen = []
            for px, py in hand_pts:
                mx = x + int((1.0 - px) * w)
                my = y + int(py * h)
                pts_screen.append((mx, my))
            hand_pts_draw = pts_screen
            for i, j in HAND_CONNECTIONS:
                dline(surface, (0, 255, 255), pts_screen[i], pts_screen[j], 2)
            for i, p in enumerate(pts_screen):
                color = MAGENTA if i in FINGER_TIPS else (0, 200, 255)
                dcircle(surface, color, p, 4)
        elif current_mode == 2 and track_source == "FACE" and cam_feed is not None and face_pts:
            fh, fw = cam_feed.shape[:2]
            pts_screen = []
            for px, py in face_pts:
                mx = x + int((1.0 - px) * w)
                my = y + int(py * h)
                pts_screen.append((mx, my))
            face_pts_draw = pts_screen
            for i, j in FACE_CONNECTIONS:
                dline(surface, (0, 255, 255), pts_screen[i], pts_screen[j], 1)
            nose = pts_screen[FACE_NOSE_TIP]
            dcircle(surface, MAGENTA, nose, 5)
            dcircle(surface, MAGENTA, nose, 9, 2)
            dline(surface, MAGENTA, (nose[0] - 12, nose[1]), (nose[0] + 12, nose[1]), 2)
            dline(surface, MAGENTA, (nose[0], nose[1] - 12), (nose[0], nose[1] + 12), 2)
        else:
            hand_pts_draw = []
            face_pts_draw = []

    if show_beam and show_dot:
        mx, my = display_aim(servo_pan, servo_tilt)
        dot_x, dot_y = project_dot(mx, my, x, y, w, h)
        dot_x = max(x + 2, min(x + w - 2, dot_x))
        dot_y = max(y + 2, min(y + h - 2, dot_y))
        for r in range(16, 5, -3):
            a = max(10, 55 - r * 4)
            gs = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            dcircle(gs, (255, 40, 40, a), (r, r), r)
            surface.blit(gs, (dot_x - r, dot_y - r))
        dcircle(surface, LASER, (dot_x, dot_y), 4)
        cs = 10
        dline(surface, (255, 255, 255), (dot_x - cs, dot_y), (dot_x + cs, dot_y), 2)
        dline(surface, (255, 255, 255), (dot_x, dot_y - cs), (dot_x, dot_y + cs), 2)

    if hit_ring > 0:
        a = int(200 * hit_ring)
        hr = int(22 + 40 * (1.0 - hit_ring))
        ss = pygame.Surface((30, 30), pygame.SRCALPHA)
        dcircle(ss, (255, 200, 0, a), (15, 15), hr, 3)
        dcircle(ss, (255, 200, 0, a // 3), (15, 15), max(hr // 2, 3))
        surface.blit(ss, (hit_x - 15, hit_y - 15))

    draw_wall_status(surface, x, y, w, h)


def draw_system_strip(surface, x, y, w, h):
    """Five status tiles in the free space below the wall view."""
    draw_frame(surface, (x, y, w, h), GREEN_DIM)
    online = link.connected
    track_ready = ((track_source == "HAND" and hand_ok) or
                   (track_source == "FACE" and face_ok) or
                   (track_source == "BODY" and pose_ok))
    if isinstance(target_cam_idx, str):
        cam_txt, cam_col = "IP STREAM", CYAN
    elif target_ok or camera_ok:
        cam_txt, cam_col = "LOCAL CAM", CYAN
    else:
        cam_txt, cam_col = "VIRTUAL", GRAY
    tiles = [
        ("LINK", "ONLINE" if online else "OFFLINE", GREEN if online else RED),
        ("LASER", "ON" if link_engage else "SAFE", RED if link_engage else GREEN_MID),
        ("TRACK", "READY" if track_ready else "IDLE", MAGENTA if track_ready else ORANGE),
        ("WALL CAM", cam_txt, cam_col),
        ("SAFETY", "2s WATCHDOG", GREEN_MID),
    ]
    tile_w = (w - 16) // len(tiles)
    for i, (name, val, col) in enumerate(tiles):
        tx = x + 8 + i * tile_w
        box = (tx, y + 7, tile_w - 8, h - 14)
        drect(surface, (8, 16, 12), box)
        drect(surface, DARK_GRAY, box, 1)
        pulse = 0.6 + 0.4 * math.sin(time.time() * 2.0 + i)
        draw_led(surface, (tx + 10, y + 17), col, 3, pulse)
        surface.blit(FONT_XS.render(name, True, GRAY), (tx + 18, y + 9))
        surface.blit(FONT_S.render(val, True, col), (tx + 8, y + 27))


def draw_hud(surface, x, y, w=290):
    total_h = HEIGHT - y - 4
    draw_frame(surface, (x, y, w, total_h), GREEN_DIM)
    # --- beam state chip, with a pulsing lamp ---
    armed = link_engage
    state_col = RED if armed else GREEN_MID
    chip = (x + 8, y + 6, w - 16, 26)
    drect(surface, (46, 8, 12) if armed else (8, 22, 13), chip)
    drect(surface, state_col, chip, 1)
    pulse = 0.55 + 0.45 * math.sin(time.time() * (9.0 if armed else 2.5))
    draw_led(surface, (x + 21, y + 19), state_col, 5, pulse)
    surface.blit(FONT_B.render("LASER ON" if armed else "LASER SAFE", True, state_col),
                 (x + 33, y + 9))
    sub = FONT_XS.render("HOLD" if armed else "INHIBITED", True, state_col)
    surface.blit(sub, (x + w - 10 - sub.get_width(), y + 16))

    py = y + 38

    def add(text, color, font):
        nonlocal py
        if text:
            surface.blit(font.render(text, True, color), (x + 10, py))
        py += font.get_height() + 2

    def sep():
        nonlocal py
        py += 2
        dline(surface, DARK_GRAY, (x + 8, py), (x + w - 8, py), 1)
        py += 4

    def section(title):
        nonlocal py
        drect(surface, (8, 20, 12), (x + 8, py, w - 16, 14))
        surface.blit(FONT_XB.render(title, True, GREEN_MID), (x + 12, py + 1))
        py += 16

    section("POSITION / BEAM")
    card = (x + 8, py, w - 16, 46)
    drect(surface, (8, 16, 12), card)
    drect(surface, GREEN_DIM, card, 1)
    half = (w - 16) // 2
    dline(surface, GREEN_DIM, (x + 8 + half, py), (x + 8 + half, py + 46), 1)
    # X / PAN with travel slider (centre notch = X100).
    surface.blit(FONT_XS.render("X / PAN", True, GRAY), (x + 14, py + 2))
    surface.blit(FONT_B.render(f"{servo_pan:05.1f}", True, CYAN), (x + 14, py + 14))
    bx_w = half - 16
    drect(surface, (14, 26, 18), (x + 14, py + 36, bx_w, 4))
    dline(surface, GRAY, (x + 14 + bx_w // 2, py + 35),
          (x + 14 + bx_w // 2, py + 41), 1)
    # Slider dots follow the wall dot direction, not raw servo direction.
    mx, my = display_aim(servo_pan, servo_tilt)
    wx, wy = project_dot(mx, my, WALL_X, WALL_Y, WALL_W, WALL_H)
    pct_x = max(0.0, min(1.0, (wx - WALL_X) / WALL_W))
    dcircle(surface, CYAN, (x + 14 + int(pct_x * bx_w), py + 38), 2)
    # Y / TILT with travel slider (centre notch = Y80).
    surface.blit(FONT_XS.render("Y / TILT", True, GRAY), (x + 14 + half, py + 2))
    surface.blit(FONT_B.render(f"{servo_tilt:05.1f}", True, CYAN), (x + 14 + half, py + 14))
    drect(surface, (14, 26, 18), (x + 14 + half, py + 36, bx_w, 4))
    dline(surface, GRAY, (x + 14 + half + bx_w // 2, py + 35),
          (x + 14 + half + bx_w // 2, py + 41), 1)
    pct_y = max(0.0, min(1.0, (wy - WALL_Y) / WALL_H))
    dcircle(surface, CYAN, (x + 14 + half + int(pct_y * bx_w), py + 38), 2)
    py += 50
    az_now, el_now = kin.beam_angles(servo_pan, servo_tilt)
    add(f"az {az_now:+06.1f}   el {el_now:+06.1f}", GREEN_MID, FONT_S)
    sep()
    section("MODE / OPTICS")

    add("MODE: " + ["MANUAL", "HAND/FACE", "ENEMY TRACK"][current_mode - 1],
        YELLOW, FONT_B)
    if centre_hold:
        add("CENTRE HOLD (all modes)", YELLOW, FONT_S)
        _cb_az, _cb_el = active_centre_bias()
        add(f"BIAS az {_cb_az:+.2f} el {_cb_el:+.2f}", CYAN, FONT_XS)
    if distance_entry_active:
        add(f"DIST ENTRY {distance_entry_text or '0'} cm", YELLOW, FONT_XS)
    else:
        add(f"DIST {active_distance_cm():.0f} cm  ([ ] / N)", CYAN, FONT_XS)
    add(f"FOV H {CAM_HFOV_DEG:.1f}  V {CAM_VFOV_DEG:.1f}", GRAY, FONT_XS)
    if camera_url_entry_active:
        add(f"URL {camera_url_text}", YELLOW, FONT_XS)
    elif TARGET_CAMERA_URL:
        add("PHONE CAM ACTIVE", CYAN, FONT_XS)
    sep()
    section("TRACK / LOCK")
    _track_ready = ((track_source == "HAND" and hand_ok) or
                    (track_source == "FACE" and face_ok) or
                    (track_source == "BODY" and pose_ok))
    add("TRACK: " + track_source, MAGENTA if _track_ready else ORANGE, FONT_B)
    if current_mode == 1:
        add("INPUT: " + manual_input, GREEN if manual_input == "STICK" else CYAN, FONT_S)
        if not laser_on and not centre_hold:
            add("PRESS SPACE TO ARM", YELLOW, FONT_S)
        if joy is not None:
            add("STICK: " + joy.get_name(), GRAY, FONT_XS)
    elif current_mode == 2:
        if track_source == "HAND":
            if hand_ok and hand_detected:
                hx = "%.0f" % ((1.0 - hand_x) * 100)
                hy = "%.0f" % (hand_y * 100)
                gcol = GREEN if hand_gesture == "FIST" else CYAN if hand_gesture == "OPEN" else YELLOW
                add(f"HAND {hx:>3}% {hy:>3}%  {hand_gesture}", gcol, FONT_S)
            else:
                add("HAND: NOT FOUND", RED, FONT_S)
        else:
            if face_ok and face_detected:
                add(f"HEAD Y{head_yaw:+05.1f} P{head_pitch:+05.1f} R{head_roll:+05.1f}",
                    GREEN, FONT_XS)
                if recog_ready and recog_user:
                    add(f"ID {recog_user} {recog_conf * 100.0:.0f}%", GREEN, FONT_XS)
            else:
                add("FACE: NOT FOUND", RED, FONT_S)
    else:
        _lock_label = {"HAND": "HAND / PALM", "FACE": "HEAD / FACE",
                       "BODY": "BODY / TORSO"}.get(track_source, track_source)
        add("LOCK: " + _lock_label, MAGENTA, FONT_S)
        if enemy_detected:
            add(f"TARGET {enemy_x * 100:3.0f}% / {enemy_y * 100:3.0f}%", GREEN, FONT_S)
        else:
            add("TARGET: NOT FOUND", RED, FONT_S)
            add("holding last aim", GRAY, FONT_XS)
    sep()

    section("CONTROLS")
    # Compact three-column key map: every command stays visible in the panel.
    rows = [
        ("1 MAN", "2 HAND", "3 ENEMY"),
        ("R CTR", "[ ] CM", "N TYPE"),
        ("T SRC", "G I/O", "Z ZERO"),
        ("M MASK", "H DOT", "P PIP"),
        ("C CTR", "E ENROLL", "+/- THR"),
        ("Y TCAM", "U UCAM", "L LINK"),
        (", . HFOV", "; ' VFOV", "V URL"),
        ("SPACE", "ENTER", "ARROWS / ESC"),
        ("F9 WINDOW", "F10 FULL", "F11 TOGGLE"),
    ]
    col_w = w // 3
    for left, mid, right in rows:
        for j, txt in enumerate((left, mid, right)):
            if txt:
                surface.blit(FONT_XS.render(txt, True, GRAY),
                             (x + 8 + j * col_w, py))
        py += FONT_XS.get_height() + 2


_grab_joystick()

running = True
while running:
    dt = clock.tick(60) / 1000.0

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
              and not setup_active):
            mp = scene_pos(event.pos)
            tab_hit = False
            for i, rect in enumerate(mode_tab_rects()):
                if rect.collidepoint(mp):
                    set_mode(i + 1)
                    tab_hit = True
                    break
            if not tab_hit and show_pip and pip_rect.collidepoint(mp):
                pip_drag = True
                pip_drag_off = (mp[0] - pip_rect.x, mp[1] - pip_rect.y)
        elif event.type == pygame.MOUSEMOTION and pip_drag:
            mp = scene_pos(event.pos)
            pip_rect.x = max(0, min(WIDTH - pip_rect.w, mp[0] - pip_drag_off[0]))
            pip_rect.y = max(0, min(HEIGHT - pip_rect.h, mp[1] - pip_drag_off[1]))
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and pip_drag:
            pip_drag = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_F9:
                set_display_mode("window")
            elif event.key == pygame.K_F10:
                set_display_mode("full")
            elif event.key == pygame.K_F11:
                toggle_display_mode()
            elif setup_active:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_TAB:
                    setup_selected = 1 - setup_selected
                elif event.key == pygame.K_RETURN:
                    setup_active = False
                    print("[Setup] Done — entering main sim")
                else:
                    for d in range(8):
                        if event.key == getattr(pygame, f"K_{d}"):
                            ok = assign_user_camera(d) if setup_selected == 0 else assign_target_camera(d)
                            if not ok:
                                print(f"[Setup] Camera index {d} not available/assignable")
                            break
            elif distance_entry_active:
                if event.key == pygame.K_RETURN:
                    try:
                        cm = float(distance_entry_text)
                    except ValueError:
                        cm = active_distance_cm()
                    cm = set_active_distance_cm(cm)
                    distance_entry_active = False
                    distance_entry_text = ""
                    print(f"[Distance] set to {cm:.0f} cm (typed)")
                elif event.key == pygame.K_ESCAPE:
                    distance_entry_active = False
                    distance_entry_text = ""
                    print("[Distance] entry cancelled")
                elif event.key == pygame.K_BACKSPACE:
                    distance_entry_text = distance_entry_text[:-1]
                elif event.unicode.isdigit():
                    distance_entry_text += event.unicode
            elif camera_url_entry_active:
                if event.key == pygame.K_RETURN:
                    url = camera_url_text.strip()
                    if url and assign_target_camera(url):
                        print(f"[Camera] direct stream active: {url}")
                    else:
                        print("[Camera] stream open FAILED")
                    camera_url_entry_active = False
                    camera_url_text = ""
                elif event.key == pygame.K_ESCAPE:
                    camera_url_entry_active = False
                    camera_url_text = ""
                    print("[Camera] URL entry cancelled")
                elif event.key == pygame.K_BACKSPACE:
                    camera_url_text = camera_url_text[:-1]
                elif event.unicode:
                    camera_url_text += event.unicode
            elif event.key == pygame.K_v:
                camera_url_entry_active = True
                camera_url_text = TARGET_CAMERA_URL or "http://192.168.4.3:8080/video"
                print("[Camera] type phone stream URL, Enter=connect, Esc=cancel")
            elif event.key == pygame.K_n:
                distance_entry_active = True
                distance_entry_text = str(int(active_distance_cm()))
                print("[Distance] typing mode: enter cm, Enter=set, Esc=cancel")
            elif event.key == pygame.K_COMMA:
                CAM_HFOV_DEG = max(10.0, min(80.0, CAM_HFOV_DEG - 1.0))
                print(f"[FOV] H={CAM_HFOV_DEG:.1f} V={CAM_VFOV_DEG:.1f}")
            elif event.key == pygame.K_PERIOD:
                CAM_HFOV_DEG = max(10.0, min(80.0, CAM_HFOV_DEG + 1.0))
                print(f"[FOV] H={CAM_HFOV_DEG:.1f} V={CAM_VFOV_DEG:.1f}")
            elif event.key == pygame.K_SEMICOLON:
                CAM_VFOV_DEG = max(10.0, min(80.0, CAM_VFOV_DEG - 1.0))
                print(f"[FOV] H={CAM_HFOV_DEG:.1f} V={CAM_VFOV_DEG:.1f}")
            elif event.key == pygame.K_QUOTE:
                CAM_VFOV_DEG = max(10.0, min(80.0, CAM_VFOV_DEG + 1.0))
                print(f"[FOV] H={CAM_HFOV_DEG:.1f} V={CAM_VFOV_DEG:.1f}")
            elif event.key == pygame.K_ESCAPE:
                running = False
            elif event.key == pygame.K_SPACE:
                laser_on = not laser_on
            elif event.key == pygame.K_RETURN:
                fire_flash_timer = 5
                hit_ring = 1.0
                dot_x, dot_y = project_dot(*display_aim(servo_pan, servo_tilt), WALL_X, WALL_Y, WALL_W, WALL_H)
                hit_x = max(WALL_X + 2, min(WALL_X + WALL_W - 2, dot_x))
                hit_y = max(WALL_Y + 2, min(WALL_Y + WALL_H - 2, dot_y))
            elif event.key == pygame.K_1:
                set_mode(1)
            elif event.key == pygame.K_2:
                set_mode(2)
            elif event.key == pygame.K_3:
                set_mode(3)
                print("[Mode] ENEMY TRACK (front camera) — T cycles HAND/FACE/BODY")
            elif event.key == pygame.K_r:
                centre_hold = not centre_hold
                if centre_hold:
                    src = "TARGET" if target_ok else "TRACKER"
                    print(f"[Centre] FRAME CENTRE HOLD ({src} cam, "
                          f"{active_distance_cm():.0f} cm) — laser ON; hold arrows = fine trim; Z zero; R finish")
                else:
                    print(f"[Centre] paste these at the top of main.py:\n"
                          f"ENEMY_CENTER_AZ_BIAS = {enemy_az_bias:+.2f}\n"
                          f"ENEMY_CENTER_EL_BIAS = {enemy_el_bias:+.2f}\n"
                          f"USER_CENTER_AZ_BIAS  = {user_az_bias:+.2f}\n"
                          f"USER_CENTER_EL_BIAS  = {user_el_bias:+.2f}")
            elif event.key == pygame.K_LEFTBRACKET:
                cm = nudge_distance_cm(-10.0)
                print(f"[Distance] = {cm:.0f} cm")
            elif event.key == pygame.K_RIGHTBRACKET:
                cm = nudge_distance_cm(10.0)
                print(f"[Distance] = {cm:.0f} cm")
            elif event.key == pygame.K_g:
                manual_input = "KEY" if manual_input == "STICK" else "STICK"
                aim_pan = servo_pan
                aim_tilt = servo_tilt
                print(f"[Manual] input = {manual_input}")
            elif event.key == pygame.K_o:
                _cycle_joystick()
            elif event.key == pygame.K_t:
                if current_mode == 3:
                    track_source = {"HAND": "FACE", "FACE": "BODY",
                                    "BODY": "HAND"}.get(track_source, "HAND")
                else:
                    track_source = "FACE" if track_source == "HAND" else "HAND"
                print(f"[Track] source = {track_source}")
            elif event.key == pygame.K_m:
                show_mask = not show_mask
                print(f"[Mask] overlay {'ON' if show_mask else 'OFF'}")
            elif event.key == pygame.K_h:
                show_dot = not show_dot
                print(f"[Dot] wall dot {'ON' if show_dot else 'OFF'} (laser unchanged)")
            elif event.key == pygame.K_p:
                show_pip = not show_pip
                print(f"[PIP] webcam window {'ON' if show_pip else 'OFF'}")
            elif event.key == pygame.K_z:
                if target_ok:
                    enemy_az_bias = enemy_el_bias = 0.0
                else:
                    user_az_bias = user_el_bias = 0.0
                print("[Centre] active bias ZEROED (recovery from end stop)")
            elif event.key == pygame.K_e:
                enroll_face()
            elif event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                recog_threshold = max(0.05, recog_threshold - 0.02)
                print(f"[FaceAI] match threshold = {recog_threshold:.2f}")
            elif event.key == pygame.K_MINUS:
                recog_threshold = min(0.60, recog_threshold + 0.02)
                print(f"[FaceAI] match threshold = {recog_threshold:.2f}")
            elif event.key == pygame.K_c:
                recenter_head()
                aim_pan = PAN_CENTRE
                aim_tilt = TILT_CENTRE
            elif event.key == pygame.K_y:
                cycle_target_camera()
            elif event.key == pygame.K_u:
                cycle_user_camera()
            elif event.key == pygame.K_l:
                link.reconnect()
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                fire_flash_timer = 5
                hit_ring = 1.0
                dot_x, dot_y = project_dot(*display_aim(servo_pan, servo_tilt), WALL_X, WALL_Y, WALL_W, WALL_H)
                hit_x = max(WALL_X + 2, min(WALL_X + WALL_W - 2, dot_x))
                hit_y = max(WALL_Y + 2, min(WALL_Y + WALL_H - 2, dot_y))
        elif event.type == pygame.JOYBUTTONDOWN:
            if event.button == 3:
                fire_flash_timer = 5
                hit_ring = 1.0
                dot_x, dot_y = project_dot(*display_aim(servo_pan, servo_tilt), WALL_X, WALL_Y, WALL_W, WALL_H)
                hit_x = max(WALL_X + 2, min(WALL_X + WALL_W - 2, dot_x))
                hit_y = max(WALL_Y + 2, min(WALL_Y + WALL_H - 2, dot_y))
        elif event.type == pygame.JOYDEVICEADDED:
            _grab_joystick()
        elif event.type == pygame.JOYDEVICEREMOVED:
            _grab_joystick()

    pygame.event.pump()
    if gamepad_connected:
        try:
            for i in range(min(joy.get_numaxes(), 8)):
                gamepad_axes[i] = round((joy.get_axis(i) + 1.0) * 127.5, 1)
        except Exception:
            gamepad_connected = False

    capture_camera()
    capture_target()
    if current_mode == 2:
        hand_tick += 1
        face_tick += 1
        if track_source == "HAND" and hand_tick % TRACK_TICK_EVERY == 0:
            process_hands()
        elif track_source == "FACE" and face_tick % TRACK_TICK_EVERY == 0:
            process_faces()
    elif current_mode == 3:
        enemy_tick += 1
        if enemy_tick % TRACK_TICK_EVERY == 0:
            process_enemy()

    if not setup_active:
        if centre_hold:
            # R wins in every mode: aim the beam at the active wall camera's
            # frame centre at the selected distance, with laser ON and held.
            # Hold an arrow for a FINE trim. Manual KEY uses 65 units/s for
            # flying; that speed here would slam X into its end stop in ~1 s.
            b_az, b_el = active_centre_bias()
            keys = pygame.key.get_pressed()
            kspd = R_BIAS_RATE * dt
            # Mount/servo direction is reversed vs raw az/el, so invert here:
            # LEFT/UP must move both the physical laser and wall dot that way.
            if keys[pygame.K_LEFT]:
                b_az += kspd
            if keys[pygame.K_RIGHT]:
                b_az -= kspd
            if keys[pygame.K_UP]:
                b_el -= kspd
            if keys[pygame.K_DOWN]:
                b_el += kspd
            b_az = max(-R_BIAS_LIMIT, min(R_BIAS_LIMIT, b_az))
            b_el = max(-R_BIAS_LIMIT, min(R_BIAS_LIMIT, b_el))
            if target_ok:
                enemy_az_bias, enemy_el_bias = b_az, b_el
            else:
                user_az_bias, user_el_bias = b_az, b_el

            cx, cy = aim_from_camera_point(0.0, 0.0, active_distance_cm())
            desired_pan, desired_tilt = apply_bias(cx, cy, b_az, b_el)
            # Deliberately slower than manual KEY: ease the TARGET to centre,
            # never jump. servo_step then ramps the actual servos as usual.
            move = 55.0 * dt
            target_pan += max(-move, min(move, desired_pan - target_pan))
            target_tilt += max(-move, min(move, desired_tilt - target_tilt))
            target_pan = max(PAN_MIN, min(PAN_MAX, target_pan))
            target_tilt = max(TILT_MIN, min(TILT_MAX, target_tilt))
            # Keep the tracking aim in sync so leaving R never snaps.
            aim_pan, aim_tilt = target_pan, target_tilt
        elif current_mode == 1:
            if manual_input == "STICK":
                nx = max(-1.0, min(1.0, (gamepad_axes[0] - 127.5) / 127.5))
                ny = max(-1.0, min(1.0, (gamepad_axes[1] - 127.5) / 127.5))
                if abs(nx) < 0.04 and abs(ny) < 0.04:
                    nx = 0.0
                    ny = 0.0
                # directions re-calibrated 2026-11-19 after servo re-alignment:
                # +X = pan LEFT, +Y = tilt UP
                stick_pan = PAN_CENTRE - nx * 50.0                  # stick right -> X50 (pan right)
                stick_tilt = TILT_CENTRE - ny * 60.0  # stick up (ny=-1) -> Y140 (tilt up)
                aim_pan += (stick_pan - aim_pan) * STICK_SMOOTH
                aim_tilt += (stick_tilt - aim_tilt) * STICK_SMOOTH
                target_pan = max(PAN_MIN, min(PAN_MAX, aim_pan))
                target_tilt = max(TILT_MIN, min(TILT_MAX, aim_tilt))
            else:
                keys = pygame.key.get_pressed()
                kspd = KEY_RATE * dt
                # +X = pan LEFT, +Y = tilt UP after re-alignment
                if keys[pygame.K_LEFT]:
                    target_pan = min(PAN_MAX, target_pan + kspd)
                if keys[pygame.K_RIGHT]:
                    target_pan = max(PAN_MIN, target_pan - kspd)
                if keys[pygame.K_UP]:
                    target_tilt = min(TILT_MAX, target_tilt + kspd)
                if keys[pygame.K_DOWN]:
                    target_tilt = max(TILT_MIN, target_tilt - kspd)
                lx = gamepad_axes[0]
                ly = gamepad_axes[1]
                if abs(lx - 127.5) > 8:
                    target_pan -= (lx - 127.5) * 0.015
                if abs(ly - 127.5) > 8:
                    target_tilt -= (ly - 127.5) * 0.015
                target_pan = max(PAN_MIN, min(PAN_MAX, target_pan))
                target_tilt = max(TILT_MIN, min(TILT_MAX, target_tilt))
        elif current_mode == 2:
            if track_source == "HAND" and hand_detected and hand_ok:
                wx = hand_x
                wy = hand_y
                if hand_gesture == "FIST":
                    nx = max(-1.0, min(1.0, (wx - 0.5) * 2.0))
                    ny = max(-1.0, min(1.0, (wy - 0.5) * 2.0))  # flipped 2026-11-19: hand up -> tilt up
                    az, el = direction_from_normalized(nx, ny)
                    target_pan, target_tilt = kin.aim_at_direction(az, el)
            elif track_source == "FACE" and face_detected and face_ok:
                rel_yaw = (head_yaw - HEAD_CENTER_YAW) * HEAD_YAW_FLIP
                rel_pitch = (head_pitch - HEAD_CENTER_PITCH) * HEAD_PITCH_FLIP
                az = rel_yaw * HEAD_YAW_GAIN
                el = rel_pitch * HEAD_PITCH_GAIN
                target_pan, target_tilt = kin.aim_at_direction(az, el)
            target_pan = max(PAN_MIN, min(PAN_MAX, target_pan))
            target_tilt = max(TILT_MIN, min(TILT_MAX, target_tilt))
            aim_pan += (target_pan - aim_pan) * AIM_SMOOTH
            aim_tilt += (target_tilt - aim_tilt) * AIM_SMOOTH
            target_pan, target_tilt = aim_pan, aim_tilt
        elif current_mode == 3:
            # Enemy frame point -> wall point at the chosen distance -> exact IK.
            # R = centre hold (handled above); detected target = follow;
            # lost target = hold last aim, no auto-park.
            if enemy_detected:
                # Live-fitted camera flips: image right/up maps to the opposite
                # beam side on this mount (kept from the 2026-11-20 calibration).
                nx = max(-1.0, min(1.0, (enemy_x - 0.5) * 2.0)) * ENEMY_X_FLIP
                ny = max(-1.0, min(1.0, (0.5 - enemy_y) * 2.0)) * ENEMY_Y_FLIP
                bx, by = aim_from_camera_point(nx, ny, active_distance_cm())
                b_az, b_el = active_centre_bias()
                target_pan, target_tilt = apply_bias(bx, by, b_az, b_el)
                target_pan = max(PAN_MIN, min(PAN_MAX, target_pan))
                target_tilt = max(TILT_MIN, min(TILT_MAX, target_tilt))
            aim_pan += (target_pan - aim_pan) * AIM_SMOOTH
            aim_tilt += (target_tilt - aim_tilt) * AIM_SMOOTH
            target_pan, target_tilt = aim_pan, aim_tilt

        # --- one engage state for HUD + hardware (no more screen/real mismatch) ---
        if centre_hold:                              # R: laser ON in any mode, held
            link_engage = True
        elif current_mode == 3:                      # ENEMY: laser on for lock only
            link_engage = enemy_detected
        elif current_mode == 1:                      # MANUAL: Space arms laser + motion
            link_engage = laser_on
        elif track_source == "HAND":
            link_engage = hand_detected and hand_gesture == "FIST"
        else:                                        # FACE
            link_engage = face_detected
        # HUD always shows where the beam points in STICK mode, even disarmed.
        # Hardware/laser still follow link_engage only.
        show_beam = link_engage or (current_mode == 1 and manual_input == "STICK")

        def servo_step(pos, vel, target, dt):
            max_step = SERVO_MAX_ACCEL * dt
            desired_v = max(-SERVO_MAX_VEL, min(SERVO_MAX_VEL, (target - pos) * SERVO_GAIN))
            vel += max(-max_step, min(max_step, desired_v - vel))
            pos += vel * dt
            return pos, vel

        if show_beam:                                # STICK: sim tracks even while disarmed
            servo_pan, servo_pan_v = servo_step(servo_pan, servo_pan_v, target_pan, dt)
            servo_tilt, servo_tilt_v = servo_step(servo_tilt, servo_tilt_v, target_tilt, dt)
            servo_pan = max(PAN_MIN, min(PAN_MAX, servo_pan))
            servo_tilt = max(TILT_MIN, min(TILT_MAX, servo_tilt))

        # --- turret link output: real X/Y servo angles via direction model ---
        if link_engage:
            cmd = f"S{int(round(servo_pan))},{int(round(servo_tilt))}"
        else:
            cmd = "F"
        if cmd != arm_last_cmd:
            link.write(cmd + "\n")
            arm_last_cmd = cmd
        link.service()   # heartbeat keeps the STM32 watchdog from parking

    if fire_flash_timer > 0:
        fire_flash_timer -= 1
    if hit_ring > 0:
        hit_ring = max(0.0, hit_ring - 0.03)

    screen.fill(BG)
    if setup_active:
        draw_setup_screen(screen)
    else:
        draw_hud(screen, HUD_X, HUD_Y, HUD_W)
        draw_gimbal_pose(screen, POSE_X, POSE_Y, POSE_W, POSE_H)
        draw_target_wall(screen, WALL_X, WALL_Y, WALL_W, WALL_H)
        draw_system_strip(screen, WALL_X, WALL_Y + WALL_H + 10, WALL_W, 52)
        if show_pip and camera_ok and camera_raw is not None:
            draw_tracker_pip(screen)
        draw_header(screen)

        if fire_flash_timer > 0:
            fs = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            a = int(60 * (fire_flash_timer / 5))
            fs.fill((255, 80, 20, a))
            screen.blit(fs, (0, 0))

    draw_scanlines(screen)
    present()

# Leaving the sim: send centre + laser-off before dropping the socket.
# The UART bridge accepts S<x>,<y> (engage move) and F (laser off, hold).
try:
    if link.connected:
        link.write("S100,80\n")
        link.write("F\n")
        time.sleep(0.2)          # let ESP32 forward both commands to STM32
except Exception:
    pass
link.close()
pygame.quit()
if camera_cap is not None:
    camera_cap.release()
print("[System] Simulator ended.")