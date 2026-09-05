"""
Face recognition — ArcFace ONNX embeddings + cosine matching.
Reuses MediaPipe FaceLandmarker for face location, then embeds the
aligned 112x112 crop and matches against an enrolled user database.
"""
import os
import json
import cv2
import numpy as np


class FaceRecognizer:
    def __init__(self, model_path, db_path):
        self.sess = None
        self.model_path = model_path
        self.db_path = db_path
        self.users = {}  # name -> list of 512-d embedding lists
        self.recognized = None  # (name, best_sim)
        self._load_db()

    def load_model(self):
        try:
            import onnxruntime as ort
            self.sess = ort.InferenceSession(self.model_path)
            self.inp = self.sess.get_inputs()[0].name
            self.out = self.sess.get_outputs()[0].name
            return True
        except Exception as e:
            print(f"[FaceAI] Model load failed: {e}")
            return False

    @property
    def ready(self):
        return self.sess is not None

    # ---------- persistence ----------
    def _load_db(self):
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r") as f:
                    raw = json.load(f)
                self.users = {k: [list(map(float, e)) for e in v] for k, v in raw.items()}
            except Exception as e:
                print(f"[FaceAI] DB load failed: {e}")
                self.users = {}

    def _save_db(self):
        try:
            with open(self.db_path, "w") as f:
                json.dump({k: [list(e) for e in v] for k, v in self.users.items()}, f)
        except Exception as e:
            print(f"[FaceAI] DB save failed: {e}")

    # ---------- enrollment ----------
    def enroll(self, name, embedding):
        emb = np.asarray(embedding, dtype=np.float32)
        emb = emb / (np.linalg.norm(emb) + 1e-9)
        if name not in self.users:
            self.users[name] = []
        self.users[name].append(emb.tolist())
        # keep latest 5 samples per person
        self.users[name] = self.users[name][-5:]
        self._save_db()
        print(f"[FaceAI] Enrolled '{name}' ({len(self.users[name])} samples)")

    # ---------- inference ----------
    def embed(self, face_bgr):
        """Align + embed a BGR face crop. Returns 512-d normalized vector or None."""
        if self.sess is None or face_bgr is None or face_bgr.size == 0:
            return None
        try:
            rgb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)
            rgb = cv2.resize(rgb, (112, 112), interpolation=cv2.INTER_AREA)
            rgb = (rgb.astype(np.float32) - 127.5) / 128.0
            out = self.sess.run([self.out], {self.inp: rgb[None, ...]})[0][0]
            out = out / (np.linalg.norm(out) + 1e-9)
            return out
        except Exception as e:
            print(f"[FaceAI] embed error: {e}")
            return None

    def match(self, embedding, threshold=0.30):
        """Return (name, similarity). 0 seg = poor, 1 = identical."""
        self.recognized = None
        if embedding is None or not self.users:
            return None, 0.0
        best_name = None
        best_sim = -1.0
        for name, embs in self.users.items():
            for e in embs:
                sim = float(np.dot(np.asarray(e, dtype=np.float32), embedding))
                if sim > best_sim:
                    best_sim = sim
                    best_name = name
        if best_sim >= (1.0 - threshold):
            self.recognized = (best_name, best_sim)
            return best_name, best_sim
        return None, best_sim
