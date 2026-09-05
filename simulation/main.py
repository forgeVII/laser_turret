import pygame
import math
import random
import threading
import time

pygame.init()

WIDTH, HEIGHT = 1300, 750
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("LASER TURRET SIMULATOR")
clock = pygame.time.Clock()

BG = (8, 8, 18)
GRID = (20, 20, 42)
TURRET_COL = (60, 60, 85)
TURRET_CEN = (80, 80, 105)
LASER = (255, 40, 40)
TEXT = (190, 190, 200)
GREEN = (0, 255, 136)
YELLOW = (255, 200, 0)
CYAN = (0, 200, 255)
ORANGE = (255, 140, 0)
RED = (255, 50, 50)
GRAY = (90, 90, 110)
DARK_GRAY = (45, 45, 65)
WALL_BG = (15, 15, 28)
WALL_LINE = (35, 35, 55)
MAGENTA = (255, 0, 200)

FONT_XS = pygame.font.SysFont("Consolas", 11)
FONT_S = pygame.font.SysFont("Consolas", 13)
FONT = pygame.font.SysFont("Consolas", 16)
FONT_B = pygame.font.SysFont("Consolas", 20, bold=True)
FONT_BB = pygame.font.SysFont("Consolas", 30, bold=True)

WALL_X, WALL_Y = 330, 60
WALL_W, WALL_H = 940, 529
SIDE_X, SIDE_Y = 10, 10
SIDE_W, SIDE_H = 140, 135
TOP_CX, TOP_CY = 80, 225
TOP_R = 55
HUD_X, HUD_Y = 10, 300
HUD_W = 290

servo_pan = 90.0
servo_tilt = 90.0
servo_pan_v = 0.0
servo_tilt_v = 0.0
target_pan = 90.0
target_tilt = 90.0
aim_pan = 90.0
aim_tilt = 90.0
AIM_SMOOTH = 0.35
laser_on = True
current_mode = 1
manual_input = "STICK"

SERVO_MAX_VEL = 280.0
SERVO_MAX_ACCEL = 1400.0
SERVO_GAIN = 6.0

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

HEAD_YAW_GAIN = 1.2
HEAD_PITCH_GAIN = 1.2
HEAD_PAN = 90.0
HEAD_TILT = 90.0
HEAD_CENTER_YAW = 0.0
HEAD_CENTER_PITCH = 0.0
HEAD_YAW_FLIP = -1.0
HEAD_PITCH_FLIP = 1.0

track_source = "HAND"
show_mask = True

try:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision
    import os

    base_dir = os.path.dirname(os.path.abspath(__file__))
    hand_model = os.path.join(base_dir, "hand_landmarker.task")
    face_model = os.path.join(base_dir, "face_landmarker.task")
    hand_opts = vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=hand_model),
        running_mode=vision.RunningMode.IMAGE,
        num_hands=1,
        min_hand_detection_confidence=0.4,
        min_hand_presence_confidence=0.4,
        min_tracking_confidence=0.4,
    )
    face_opts = vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=face_model),
        running_mode=vision.RunningMode.IMAGE,
        num_faces=1,
        min_face_detection_confidence=0.4,
        min_face_presence_confidence=0.4,
        min_tracking_confidence=0.4,
        output_facial_transformation_matrixes=True,
    )
    hand_lm = None
    face_lm = None
    hand_ok = True
    face_ok = True
    mp_image = mp.Image
    hand_mp = mp


    def _load_models():
        global hand_lm, face_lm
        _h = vision.HandLandmarker.create_from_options(hand_opts)
        _f = vision.FaceLandmarker.create_from_options(face_opts)
        hand_lm = _h
        face_lm = _f
        print("[Track] MediaPipe tasks API ready (hand + face)")


    threading.Thread(target=_load_models, daemon=True).start()
except FileNotFoundError:
    print("[Track] A .task model file was not found")
except Exception as e:
    print(f"[Track] Disabled: {e}")

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


def draw_tracker_pip(surface, x, y, w, h):
    pygame.draw.rect(surface, DARK_GRAY, (x, y, w, h), border_radius=4)
    lbl = FONT_XS.render("TRACKER (USER CAM)", True, GRAY)
    surface.blit(lbl, (x + 6, y + 3))
    if camera_raw is None:
        return
    try:
        frame = cv2.cvtColor(camera_raw, cv2.COLOR_BGR2RGB)
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
        frame = cv2.resize(frame, (w, h))
        surf = pygame.image.frombuffer(frame.tobytes(), (w, h), "RGB")
        surface.blit(surf, (x, y + 15))
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
        frame = cv2.resize(frame, (w, h))
        surf = pygame.image.frombuffer(frame.tobytes(), (w, h), "RGB")
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


def draw_setup_screen(surface):
    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 220))
    surface.blit(overlay, (0, 0))

    title = FONT_BB.render("CAMERA SETUP", True, YELLOW)
    surface.blit(title, (WIDTH // 2 - title.get_width() // 2, 40))
    info = FONT_S.render("Assign which camera feeds which screen. Press 0-8 to pick a camera for the selected slot.",
                         True, TEXT)
    surface.blit(info, (WIDTH // 2 - info.get_width() // 2, 80))
    info2 = FONT_S.render("TAB switch slot   |   ENTER done   |   ESC quit", True, GRAY)
    surface.blit(info2, (WIDTH // 2 - info2.get_width() // 2, 100))

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
        border = GREEN if setup_selected == slot else DARK_GRAY
        pygame.draw.rect(surface, (12, 12, 26), (bx, y0, box_w, box_h), border_radius=8)
        pygame.draw.rect(surface, border, (bx, y0, box_w, box_h), 3, border_radius=8)
        lbl = FONT_B.render(name, True, YELLOW if setup_selected == slot else TEXT)
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
                frame = cv2.resize(frame, (view_w, view_h))
                surf = pygame.image.frombuffer(frame.tobytes(), (view_w, view_h), "RGB")
                surface.blit(surf, (bx + 15, y0 + 65))
                pygame.draw.rect(surface, border, (bx + 15, y0 + 65, view_w, view_h), 1)
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


def assign_target_camera(idx):
    global target_ok, target_cap, target_raw, target_cam_idx
    if idx not in available_cameras:
        rescan_cameras()
        if idx not in available_cameras:
            probe = cv2.VideoCapture(idx)
            opened = probe.isOpened()
            probe.release()
            if not opened:
                return False
    if target_cap is not None:
        target_cap.release()
        target_cap = None
        target_ok = False
    cap = cv2.VideoCapture(idx)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        target_cap = cap
        target_ok = True
        target_cam_idx = idx
        target_raw = None
        print(f"[CamB] Target camera = index {idx}")
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


def draw_top_view(surface, cx, cy, r):
    pygame.draw.rect(surface, (15, 15, 30), (cx - r - 20, cy - r - 25, r * 2 + 40, r * 2 + 50), border_radius=5)
    for angle in range(0, 360, 15):
        rad = math.radians(angle)
        ex = cx + int((r - 5) * math.cos(rad))
        ey = cy + int((r - 5) * math.sin(rad))
        pygame.draw.line(surface, GRID, (cx, cy), (ex, ey), 1)
    for ring in range(30, r + 1, 30):
        pygame.draw.circle(surface, GRID, (cx, cy), ring, 1)

    pygame.draw.circle(surface, TURRET_COL, (cx, cy), 16)
    pygame.draw.circle(surface, TURRET_CEN, (cx, cy), 11)

    if laser_on:
        pan_rad = math.radians(servo_pan + 180)
        end_x = cx + int(r * math.cos(pan_rad))
        end_y = cy + int(r * math.sin(pan_rad))
        glow = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        for i in range(3):
            pygame.draw.line(glow, (255, 40, 40, max(15 - i * 5, 5)),
                             (r, r), (end_x - cx + r, end_y - cy + r), max(3 - i, 1))
        surface.blit(glow, (cx - r, cy - r))
        pygame.draw.line(surface, LASER, (cx, cy), (end_x, end_y), 2)
        pygame.draw.circle(surface, LASER, (end_x, end_y), 3)

    lbl = FONT_S.render("TOP", True, GRAY)
    surface.blit(lbl, (cx - lbl.get_width() // 2, cy + r + 3))
    val = FONT_XS.render(f"{servo_pan:.0f}", True, CYAN)
    surface.blit(val, (cx - val.get_width() // 2, cy + r + 17))


def draw_side_view(surface, x, y, w, h):
    pygame.draw.rect(surface, (15, 15, 30), (x, y, w, h), border_radius=5)
    pygame.draw.rect(surface, DARK_GRAY, (x, y, w, h), 1, border_radius=5)
    bx, by = x + w // 2, y + h - 15
    pygame.draw.line(surface, TURRET_COL, (bx - 12, by), (bx + 12, by), 4)
    pygame.draw.circle(surface, TURRET_COL, (bx, by - 3), 7)
    pygame.draw.circle(surface, TURRET_CEN, (bx, by - 3), 5)
    if laser_on:
        tilt_rad = math.radians(servo_tilt)
        end_x = bx + int(65 * math.cos(tilt_rad))
        end_y = by - int(65 * math.sin(tilt_rad))
        pygame.draw.line(surface, LASER, (bx, by - 3), (end_x, end_y), 2)
        pygame.draw.circle(surface, LASER, (end_x, end_y), 3)
    lbl = FONT_XS.render("SIDE", True, GRAY)
    surface.blit(lbl, (x + w // 2 - lbl.get_width() // 2, y + 3))
    val = FONT_XS.render(f"{servo_tilt:.0f}", True, CYAN)
    surface.blit(val, (x + w // 2 - val.get_width() // 2, y + h - 22))


def draw_target_wall(surface, x, y, w, h):
    cam_surf = get_camera_surface(w, h)
    if cam_surf is not None:
        surface.blit(cam_surf, (x, y))
        pygame.draw.rect(surface, GRID, (x, y, w, h), 2)
    else:
        pygame.draw.rect(surface, WALL_BG, (x, y, w, h))
        pygame.draw.rect(surface, GRID, (x, y, w, h), 1)
        for gx in range(0, w, 30):
            pygame.draw.line(surface, WALL_LINE, (x + gx, y), (x + gx, y + h), 1)
        for gy in range(0, h, 30):
            pygame.draw.line(surface, WALL_LINE, (x, y + gy), (x + w, y + gy), 1)

    if show_mask:
        cam_feed = target_raw if (target_ok and target_raw is not None) else camera_raw
        if current_mode == 2 and track_source == "HAND" and cam_feed is not None and hand_pts:
            fh, fw = cam_feed.shape[:2]
            pts_screen = []
            for px, py in hand_pts:
                mx = x + int((1.0 - px) * w)
                my = y + int(py * h)
                pts_screen.append((mx, my))
            hand_pts_draw = pts_screen
            for i, j in HAND_CONNECTIONS:
                pygame.draw.line(surface, (0, 255, 255), pts_screen[i], pts_screen[j], 2)
            for i, p in enumerate(pts_screen):
                color = MAGENTA if i in FINGER_TIPS else (0, 200, 255)
                pygame.draw.circle(surface, color, p, 4)
        elif current_mode == 2 and track_source == "FACE" and cam_feed is not None and face_pts:
            fh, fw = cam_feed.shape[:2]
            pts_screen = []
            for px, py in face_pts:
                mx = x + int((1.0 - px) * w)
                my = y + int(py * h)
                pts_screen.append((mx, my))
            face_pts_draw = pts_screen
            for i, j in FACE_CONNECTIONS:
                pygame.draw.line(surface, (0, 255, 255), pts_screen[i], pts_screen[j], 1)
            nose = pts_screen[FACE_NOSE_TIP]
            pygame.draw.circle(surface, MAGENTA, nose, 5)
            pygame.draw.circle(surface, MAGENTA, nose, 9, 2)
            pygame.draw.line(surface, MAGENTA, (nose[0] - 12, nose[1]), (nose[0] + 12, nose[1]), 2)
            pygame.draw.line(surface, MAGENTA, (nose[0], nose[1] - 12), (nose[0], nose[1] + 12), 2)
        else:
            hand_pts_draw = []
            face_pts_draw = []

    if laser_on:
        dot_x = x + int((servo_pan / 180.0) * w)
        dot_y = y + int((1.0 - servo_tilt / 180.0) * h)
        dot_x = max(x + 2, min(x + w - 2, dot_x))
        dot_y = max(y + 2, min(y + h - 2, dot_y))
        for r in range(16, 5, -3):
            a = max(10, 55 - r * 4)
            gs = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(gs, (255, 40, 40, a), (r, r), r)
            surface.blit(gs, (dot_x - r, dot_y - r))
        pygame.draw.circle(surface, LASER, (dot_x, dot_y), 4)
        cs = 10
        pygame.draw.line(surface, (255, 255, 255), (dot_x - cs, dot_y), (dot_x + cs, dot_y), 2)
        pygame.draw.line(surface, (255, 255, 255), (dot_x, dot_y - cs), (dot_x, dot_y + cs), 2)

    if hit_ring > 0:
        a = int(200 * hit_ring)
        hr = int(22 + 40 * (1.0 - hit_ring))
        ss = pygame.Surface((30, 30), pygame.SRCALPHA)
        pygame.draw.circle(ss, (255, 200, 0, a), (15, 15), hr, 3)
        pygame.draw.circle(ss, (255, 200, 0, a // 3), (15, 15), max(hr // 2, 3))
        surface.blit(ss, (hit_x - 15, hit_y - 15))


def draw_hud(surface, x, y, w=290):
    total_h = HEIGHT - y - 10
    pygame.draw.rect(surface, (12, 12, 26), (x, y, w, total_h), border_radius=6)
    pygame.draw.rect(surface, GRID, (x, y, w, total_h), 1, border_radius=6)

    py = y + 8

    def add(text, color, font):
        nonlocal py
        if text:
            lbl = font.render(text, True, color)
            surface.blit(lbl, (x + 10, py))
        py += font.get_height() + 2

    def sep():
        nonlocal py
        py += 4
        pygame.draw.line(surface, DARK_GRAY, (x + 8, py), (x + w - 8, py), 1)
        py += 6

    mode_names = ["MANUAL", "HAND/FACE"]
    laser_txt = "ON" if laser_on else "OFF"
    laser_col = GREEN if laser_on else GRAY
    add(f"LASER  {laser_txt}", laser_col, FONT_BB)
    add(f"SERVO PAN  {servo_pan:05.1f}", CYAN, FONT_S)
    add(f"SERVO TILT {servo_tilt:05.1f}", CYAN, FONT_S)
    add(f"VEL {math.fabs(servo_pan_v):05.0f}/{math.fabs(servo_tilt_v):05.0f}", GRAY, FONT_XS)
    sep()

    add("MODE: " + mode_names[current_mode - 1], YELLOW, FONT_B)
    if current_mode == 1:
        add("INPUT: " + manual_input, GREEN if manual_input == "STICK" else CYAN, FONT_S)
        add("G   toggle KEY/STICK", GRAY, FONT_XS)
        if joy is not None:
            add("STICK: " + joy.get_name(), CYAN, FONT_XS)
    wall_src = f"CAM{target_cam_idx}" if target_ok else "SELF"
    add("WALL: " + ("WEBCAM(" + wall_src + ")" if (target_ok or camera_ok) else "VIRTUAL"), GREEN if (target_ok or camera_ok) else GRAY, FONT_S)
    add("TRACK: " + track_source, MAGENTA if track_source == "HAND" and hand_ok else ORANGE, FONT_B)
    if current_mode == 2:
        if track_source == "HAND":
            if hand_ok and hand_detected:
                hx = "%.0f" % ((1.0 - hand_x) * 100)
                hy = "%.0f" % (hand_y * 100)
                gcol = GREEN if hand_gesture == "FIST" else CYAN if hand_gesture == "OPEN" else YELLOW
                add(f"HAND: {hx:>3}%  {hy:>3}%", gcol, FONT_B)
                if hand_gesture == "FIST":
                    add("FIST  > FOLLOW", GREEN, FONT_S)
                elif hand_gesture == "OPEN":
                    add("OPEN  > FREE", CYAN, FONT_S)
                else:
                    add("GESTURE PARTIAL", YELLOW, FONT_S)
            else:
                add("HAND: NOT FOUND", RED, FONT_B)
                add("show hand to camera", GRAY, FONT_XS)
        else:
            if face_ok and face_detected:
                add(f"HEAD: Y {head_yaw:+05.1f} P {head_pitch:+05.1f} R {head_roll:+05.1f}", GREEN, FONT_S)
                add(f"CTR: {HEAD_CENTER_YAW:+.1f}/{HEAD_CENTER_PITCH:+.1f}", GRAY, FONT_XS)
                add("look around = aim", CYAN, FONT_S)
                add("C = recenter", GRAY, FONT_XS)
            else:
                add("FACE: NOT FOUND", RED, FONT_B)
                add("show face to camera", GRAY, FONT_XS)
    sep()

    add("CONTROLS", GRAY, FONT_S)
    add("1   MANUAL", GRAY, FONT_XS)
    add("2   HAND/FACE TRACK", GRAY, FONT_XS)
    add("G   KEY hold / STICK abs", GRAY, FONT_XS)
    add("O   cycle gamepad", GRAY, FONT_XS)
    add("T   toggle HAND/FACE", GRAY, FONT_XS)
    add("M   mask on/off", GRAY, FONT_XS)
    add("C   recenter head", GRAY, FONT_XS)
    add("Y   cycle target cam", GRAY, FONT_XS)
    add("U   cycle user cam", GRAY, FONT_XS)
    add("SPACE Laser on/off", GRAY, FONT_XS)
    add("BTN4/ENTER fire", GRAY, FONT_XS)
    add("Arrows / stick aim", GRAY, FONT_XS)
    add("ESC quit", GRAY, FONT_XS)


_grab_joystick()

running = True
while running:
    dt = clock.tick(60) / 1000.0

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            if setup_active:
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
            elif event.key == pygame.K_ESCAPE:
                running = False
            elif event.key == pygame.K_SPACE:
                laser_on = not laser_on
            elif event.key == pygame.K_RETURN:
                fire_flash_timer = 5
                hit_ring = 1.0
                dot_x = WALL_X + int((servo_pan / 180.0) * WALL_W)
                dot_y = WALL_Y + int((1.0 - servo_tilt / 180.0) * WALL_H)
                hit_x = max(WALL_X + 2, min(WALL_X + WALL_W - 2, dot_x))
                hit_y = max(WALL_Y + 2, min(WALL_Y + WALL_H - 2, dot_y))
            elif event.key == pygame.K_1:
                current_mode = 1
            elif event.key == pygame.K_2:
                current_mode = 2
            elif event.key == pygame.K_3:
                current_mode = 2
            elif event.key == pygame.K_g:
                manual_input = "KEY" if manual_input == "STICK" else "STICK"
                aim_pan = servo_pan
                aim_tilt = servo_tilt
                print(f"[Manual] input = {manual_input}")
            elif event.key == pygame.K_o:
                _cycle_joystick()
            elif event.key == pygame.K_t:
                track_source = "FACE" if track_source == "HAND" else "HAND"
            elif event.key == pygame.K_m:
                show_mask = not show_mask
                print(f"[Mask] overlay {'ON' if show_mask else 'OFF'}")
            elif event.key == pygame.K_c:
                recenter_head()
                aim_pan = 90.0
                aim_tilt = 90.0
            elif event.key == pygame.K_y:
                cycle_target_camera()
            elif event.key == pygame.K_u:
                cycle_user_camera()
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                fire_flash_timer = 5
                hit_ring = 1.0
                dot_x = WALL_X + int((servo_pan / 180.0) * WALL_W)
                dot_y = WALL_Y + int((1.0 - servo_tilt / 180.0) * WALL_H)
                hit_x = max(WALL_X + 2, min(WALL_X + WALL_W - 2, dot_x))
                hit_y = max(WALL_Y + 2, min(WALL_Y + WALL_H - 2, dot_y))
        elif event.type == pygame.JOYBUTTONDOWN:
            if event.button == 3:
                fire_flash_timer = 5
                hit_ring = 1.0
                dot_x = WALL_X + int((servo_pan / 180.0) * WALL_W)
                dot_y = WALL_Y + int((1.0 - servo_tilt / 180.0) * WALL_H)
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
        if track_source == "HAND" and hand_tick % 2 == 0:
            process_hands()
        elif track_source == "FACE" and face_tick % 2 == 0:
            process_faces()

    if not setup_active:
        if current_mode == 1:
            if manual_input == "STICK":
                nx = max(-1.0, min(1.0, (gamepad_axes[0] - 127.5) / 127.5))
                ny = max(-1.0, min(1.0, (gamepad_axes[1] - 127.5) / 127.5))
                if abs(nx) < 0.04 and abs(ny) < 0.04:
                    nx = 0.0
                    ny = 0.0
                stick_pan = max(0, min(180, 90 + nx * 70))
                stick_tilt = max(0, min(180, 90 - ny * 70))
                aim_pan += (stick_pan - aim_pan) * 0.4
                aim_tilt += (stick_tilt - aim_tilt) * 0.4
                target_pan = max(0, min(180, aim_pan))
                target_tilt = max(0, min(180, aim_tilt))
            else:
                keys = pygame.key.get_pressed()
                kspd = 55.0 * dt
                if keys[pygame.K_LEFT]:
                    target_pan = max(0, target_pan - kspd)
                if keys[pygame.K_RIGHT]:
                    target_pan = min(180, target_pan + kspd)
                if keys[pygame.K_UP]:
                    target_tilt = min(180, target_tilt + kspd)
                if keys[pygame.K_DOWN]:
                    target_tilt = max(0, target_tilt - kspd)
                lx = gamepad_axes[0]
                ly = gamepad_axes[1]
                if abs(lx - 127.5) > 8:
                    target_pan += (lx - 127.5) * 0.015
                if abs(ly - 127.5) > 8:
                    target_tilt -= (ly - 127.5) * 0.015
                target_pan = max(0, min(180, target_pan))
                target_tilt = max(0, min(180, target_tilt))
        elif current_mode == 2:
            if track_source == "HAND" and hand_detected and hand_ok:
                wx = 1.0 - hand_x
                wy = hand_y
                if hand_gesture == "FIST":
                    target_pan = max(0, min(180, wx * 180))
                    target_tilt = max(0, min(180, (1.0 - wy) * 180))
            elif track_source == "FACE" and face_detected and face_ok:
                rel_yaw = (head_yaw - HEAD_CENTER_YAW) * HEAD_YAW_FLIP
                rel_pitch = (head_pitch - HEAD_CENTER_PITCH) * HEAD_PITCH_FLIP
                target_pan = max(0, min(180, 90 + rel_yaw * HEAD_YAW_GAIN))
                target_tilt = max(0, min(180, 90 - rel_pitch * HEAD_PITCH_GAIN))
            target_pan = max(0, min(180, target_pan))
            target_tilt = max(0, min(180, target_tilt))
            aim_pan += (target_pan - aim_pan) * AIM_SMOOTH
            aim_tilt += (target_tilt - aim_tilt) * AIM_SMOOTH
            target_pan, target_tilt = aim_pan, aim_tilt

        def servo_step(pos, vel, target, dt):
            max_step = SERVO_MAX_ACCEL * dt
            desired_v = max(-SERVO_MAX_VEL, min(SERVO_MAX_VEL, (target - pos) * SERVO_GAIN))
            vel += max(-max_step, min(max_step, desired_v - vel))
            pos += vel * dt
            return pos, vel

        servo_pan, servo_pan_v = servo_step(servo_pan, servo_pan_v, target_pan, dt)
        servo_tilt, servo_tilt_v = servo_step(servo_tilt, servo_tilt_v, target_tilt, dt)
        servo_pan = max(0, min(180, servo_pan))
        servo_tilt = max(0, min(180, servo_tilt))

    if fire_flash_timer > 0:
        fire_flash_timer -= 1
    if hit_ring > 0:
        hit_ring = max(0.0, hit_ring - 0.03)

    screen.fill(BG)
    if setup_active:
        draw_setup_screen(screen)
    else:
        draw_hud(screen, HUD_X, HUD_Y, HUD_W)
        draw_top_view(screen, TOP_CX, TOP_CY, TOP_R)
        draw_side_view(screen, SIDE_X, SIDE_Y, SIDE_W, SIDE_H)
        draw_target_wall(screen, WALL_X, WALL_Y, WALL_W, WALL_H)
        if camera_ok and camera_raw is not None:
            pip_w, pip_h = 260, 155
            draw_tracker_pip(screen, WALL_X + WALL_W - pip_w - 8, WALL_Y + WALL_H - pip_h - 8, pip_w, pip_h)

        if fire_flash_timer > 0:
            fs = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            a = int(60 * (fire_flash_timer / 5))
            fs.fill((255, 80, 20, a))
            screen.blit(fs, (0, 0))

    pygame.display.flip()

pygame.quit()
if camera_cap is not None:
    camera_cap.release()
print("[System] Simulator ended.")