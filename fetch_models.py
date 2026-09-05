"""Download the models needed to run the laser turret simulator.

Run from the repo root:
    python fetch_models.py

Skips files that already exist. Large models (arcface.onnx ~130 MB) are
gitignored, so a fresh clone just needs this one command before running.
"""
import os
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.join(ROOT, "simulation")

MODELS = {
    # name -> download URL
    "arcface.onnx": "https://huggingface.co/garavv/arcface-onnx/resolve/main/arc.onnx",
    "hand_landmarker.task": "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
    "face_landmarker.task": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
}


def fetch(name, url):
    dst = os.path.join(SIM, name)
    if os.path.exists(dst) and os.path.getsize(dst) > 1000:
        mb = os.path.getsize(dst) // 1024 // 1024
        print(f"[models] {name} already present ({mb} MB)")
        return
    print(f"[models] downloading {name} ...")
    try:
        r = subprocess.run(
            ["curl.exe", "-L", "--fail", "-o", dst, url],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        part = dst + ".part"
        tmp = dst + ".tmp"
        with urllib.request.urlopen(url, timeout=180) as resp, open(tmp, "wb") as out:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
        os.replace(tmp, dst)
    mb = os.path.getsize(dst) // 1024 // 1024
    print(f"[models] {name} saved ({mb} MB)")


def main():
    os.makedirs(SIM, exist_ok=True)
    for name, url in MODELS.items():
        fetch(name, url)
    print("[models] done — run: python simulation/main.py")


if __name__ == "__main__":
    main()