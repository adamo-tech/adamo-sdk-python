"""YOLO object detection → SDK push.

Runs YOLOv8n on each frame, draws bounding boxes + labels,
then streams the annotated video through Adamo.

Usage:
    pip install ultralytics opencv-python
    python stream_yolo.py
"""

import cv2
import numpy as np
from ultralytics import YOLO
from adamo_video import Robot

API_KEY = "ak_2M3T7rqPYGubJO2gBsxRoWswKn83z0L6"
RELAY = "https://lhr.moq.adamohq.com/anon"

model = YOLO("yolov8n.pt")

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

print("Streaming YOLO detections (Ctrl+C to stop)...")

try:
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Camera read failed")
            break

        results = model(frame, verbose=False)

        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                label = f"{model.names[cls]} {conf:.2f}"

                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, label, (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
        track.send(frame)
except KeyboardInterrupt:
    pass
finally:
    cap.release()
