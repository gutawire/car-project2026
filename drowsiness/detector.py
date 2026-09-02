"""Eye-open/eye-closed detection for incoming camera frames.

MediaPipe's Face Landmarker (the accurate, EAR-based approach) was evaluated
and ruled out on this hardware: its compiled binary requires AES CPU
extensions that this Raspberry Pi 4's Cortex-A72 does not expose, which
crashes the whole process with an illegal instruction (SIGILL) -- not a
catchable Python exception. Haar cascades (bundled with OpenCV) are used
instead: reliable to run, no native-crash risk, good enough for this demo.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import cv2
import numpy as np

EyeState = Literal["open", "closed", "no_face"]
Box = tuple[int, int, int, int]  # (x, y, w, h) in the input frame's own pixel space


@dataclass
class Detection:
    state: EyeState
    face: Box | None = None
    eyes: list[Box] = field(default_factory=list)

_CASCADE_DIR = Path(__file__).parent.parent / "assets" / "haarcascades"
_face_cascade = cv2.CascadeClassifier(str(_CASCADE_DIR / "haarcascade_frontalface_default.xml"))
_eye_cascade = cv2.CascadeClassifier(str(_CASCADE_DIR / "haarcascade_eye_tree_eyeglasses.xml"))

if _face_cascade.empty() or _eye_cascade.empty():
    raise RuntimeError(f"Failed to load Haar cascade files from {_CASCADE_DIR}")

# Smallest face box (px) accepted at 320x240. Depends on phone-mount
# distance - raise it if the background starts getting picked up as a
# "face", lower it if a correctly-mounted driver is read as "no_face".
FACE_MIN_SIZE = (60, 60)
EYE_MIN_SIZE = (20, 20)


def detect(frame: np.ndarray) -> Detection:
    """Classify a BGR frame and report the face/eye boxes found, in the
    frame's own pixel coordinates - lets a caller draw them on the original
    image without redoing the detection."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)

    faces = _face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=FACE_MIN_SIZE)
    if len(faces) == 0:
        return Detection(state="no_face")

    # Largest detected face = the driver (closest to camera).
    x, y, w, h = (int(v) for v in max(faces, key=lambda f: f[2] * f[3]))
    # Eyes sit in the upper ~60% of the face box; excluding the lower part
    # (nose/mouth) cuts down false eye detections.
    roi = gray[y:y + int(h * 0.6), x:x + w]

    eyes = _eye_cascade.detectMultiScale(roi, scaleFactor=1.1, minNeighbors=6, minSize=EYE_MIN_SIZE)
    # Eye boxes come back relative to the cropped ROI - shift by the face's
    # own offset so callers get coordinates in the original frame.
    absolute_eyes = [(x + int(ex), y + int(ey), int(ew), int(eh)) for ex, ey, ew, eh in eyes]

    state: EyeState = "open" if len(eyes) >= 1 else "closed"
    return Detection(state=state, face=(x, y, w, h), eyes=absolute_eyes)


def eye_state(frame: np.ndarray) -> EyeState:
    """Classify a BGR frame as "open", "closed", or "no_face"."""
    return detect(frame).state


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python -m drowsiness.detector <image_path>")
        raise SystemExit(1)

    img = cv2.imread(sys.argv[1])
    if img is None:
        print(f"Could not read image: {sys.argv[1]}")
        raise SystemExit(1)

    print(eye_state(img))
