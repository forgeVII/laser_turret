import os
import sys
import time

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
import serial

SERIAL_PORT = "COM4"
BAUD = 115200
TASK_PATH = os.path.join(os.path.dirname(__file__), "..", "simulation", "hand_landmarker.task")

WRIST = 0
THUMB_TIP = 4
INDEX_MCP = 5
FINGERS = [(8, 6), (12, 10), (16, 14), (20, 18)]  # (tip, pip)


def _dist(a, b):
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def classify(lm):
    """Return True if hand is a fist."""
    fist = False
    ext = 0
    for tip_id, pip_id in FINGERS:
        if _dist(lm[tip_id], lm[WRIST]) > _dist(lm[pip_id], lm[WRIST]):
            ext += 1
    # thumb extended if tip far from index MCP
    if _dist(lm[THUMB_TIP], lm[INDEX_MCP]) > _dist(lm[2], lm[INDEX_MCP]):
        ext += 1
    fist = ext <= 1
    return fist


def main():
    ser = serial.Serial(SERIAL_PORT, BAUD, timeout=0.1)
    opts = vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=os.path.abspath(TASK_PATH)),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.4,
        min_hand_presence_confidence=0.4,
        min_tracking_confidence=0.4,
    )
    lm = vision.HandLandmarker.create_from_options(opts)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Webcam failed to open")
        sys.exit(1)

    engaged = False
    last_angle = None
    ts = 0
    print("Open palm = free | Fist = engage+follow. ESC to quit.")

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame = cv2.flip(frame, 1)  # mirror for natural left/right
        ts += 1
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
        res = lm.detect_for_video(mp_img, ts)
        hand = res.hand_landmarks[0] if res.hand_landmarks else None

        if hand:
            fist = classify(hand)
            if fist:
                if not engaged:
                    engaged = True
                    print("[engaged] laser ON")
                angle = int((1.0 - hand[WRIST].x) * 180)  # mirror: right hand -> right
                angle = max(0, min(180, angle))
                if angle != last_angle:
                    ser.write(f"S{angle}\n".encode())
                    last_angle = angle
            else:
                if engaged:
                    engaged = False
                    last_angle = None
                    ser.write(b"F\n")
                    print("[free] laser OFF")
        else:
            if engaged:
                engaged = False
                last_angle = None
                ser.write(b"F\n")
                print("[free] hand lost")

        if cv2.waitKey(1) & 0xFF == 27:
            break

    ser.write(b"F\n")
    ser.close()
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()