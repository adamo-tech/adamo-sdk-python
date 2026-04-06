"""Test 3: Numpy processing -> SDK push.

Captures frames, applies numpy operations (invert, flip — standing in for
real perception/overlay work), then pushes through SDK -> VideoToolbox -> MoQ.

Usage:
    pip install opencv-python numpy
    python stream_numpy.py
"""

import cv2
import numpy as np
from adamo_video import Robot

API_KEY = "ak_2M3T7rqPYGubJO2gBsxRoWswKn83z0L6"

robot = Robot(api_key=API_KEY, name="mac-test")
track = robot.video(
    "webcam",
    width=1280,
    height=720,
    pixel_format="BGRA",
    bitrate_kbps=4000,
    fps=30,
)

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

print("Streaming numpy-processed frames (Ctrl+C to stop)...")

try:
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Camera read failed")
            break

        # Apply some operations
        frame = 255 - frame                   # invert colors
        frame = np.flipud(frame)              # flip vertically
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
        frame = np.ascontiguousarray(frame)   # ensure C-contiguous for buffer protocol

        track.send(frame)
except KeyboardInterrupt:
    pass
finally:
    cap.release()
