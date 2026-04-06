"""Test 2: OpenCV capture -> SDK push.

User owns the camera via OpenCV (common in robotics for perception alongside
streaming). Reads BGR frames, pushes into SDK -> VideoToolbox -> MoQ.

Usage:
    pip install opencv-python
    python stream_opencv.py
"""

import cv2
from adamo_video import Robot

API_KEY = "ak_2M3T7rqPYGubJO2gBsxRoWswKn83z0L6"

RELAY = "https://lhr.moq.adamohq.com/anon"

robot = Robot(api_key=API_KEY, name="mac-test", relay=RELAY)
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

print("Streaming OpenCV frames (Ctrl+C to stop)...")

try:
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Camera read failed")
            break
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
        track.send(frame)
except KeyboardInterrupt:
    pass
finally:
    cap.release()
