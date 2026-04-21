"""YOLOv8 → Mac VideoToolbox → Zenoh teleop demo.

Captures the webcam, runs YOLOv11n on MPS for real-time object detection,
draws bounding boxes + labels + FPS, and streams the annotated video
through the Adamo SDK (iceoryx2 → vtenc_h264 → Zenoh).

Usage:
    pip install ultralytics opencv-python
    python stream_yolo.py
"""
from __future__ import annotations

import time
from collections import deque

import cv2
import numpy as np
from ultralytics import YOLO

import adamo

API_KEY = "ak_2M3T7rqPYGubJO2gBsxRoWswKn83z0L6"
WIDTH, HEIGHT, FPS = 960, 540, 30
CAMERA_INDEX = 0
CONF_THRESHOLD = 0.35

# Fixed deterministic colours per COCO class id (looks consistent frame-to-frame)
_rng = np.random.default_rng(42)
PALETTE = (_rng.random((80, 3)) * 255).astype(np.uint8)

model = YOLO("yolo11n.pt")
model.to("mps")  # Apple Silicon GPU

robot = adamo.Robot(api_key=API_KEY, name="mac-test")
track = robot.video(
    "yolo",
    width=WIDTH,
    height=HEIGHT,
    pixel_format="BGRA",
    bitrate_kbps=6000,
    fps=FPS,
)

cap = cv2.VideoCapture(CAMERA_INDEX)
# Capture at native 720p (webcams all support this). Downscale in software
# to WIDTH×HEIGHT below. Requesting non-native resolutions sometimes makes
# cv2.VideoCapture fail on the first read.
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
cap.set(cv2.CAP_PROP_FPS, FPS)

if not cap.isOpened():
    raise SystemExit(f"Could not open camera {CAMERA_INDEX}")

print(f"Streaming YOLOv11n detections @ {WIDTH}x{HEIGHT}. Ctrl+C to stop.")

frame_times = deque(maxlen=30)
count = 0
interval = 1.0 / FPS
loop_start = time.monotonic()

try:
    while True:
        t0 = time.monotonic()
        ok, frame = cap.read()
        if not ok:
            print("Camera read failed")
            break

        # Force target resolution — some webcams give you back a different one
        if frame.shape[1] != WIDTH or frame.shape[0] != HEIGHT:
            frame = cv2.resize(frame, (WIDTH, HEIGHT))

        # YOLOv8 on MPS at 416px — ~2x faster than default 640 with small accuracy cost
        results = model.predict(
            frame, verbose=False, conf=CONF_THRESHOLD, device="mps", imgsz=416,
        )

        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                color = tuple(int(c) for c in PALETTE[cls % len(PALETTE)])
                label = f"{model.names[cls]} {conf:.2f}"

                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                cv2.rectangle(frame, (x1, y1 - th - 10), (x1 + tw + 8, y1), color, -1)
                cv2.putText(
                    frame, label, (x1 + 4, y1 - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2, cv2.LINE_AA,
                )

        frame_times.append(time.monotonic() - t0)
        fps = len(frame_times) / sum(frame_times) if frame_times else 0.0

        bgra = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
        track.send(bgra)

        count += 1
        if count % (FPS * 3) == 0:
            print(f"[{count:5d}] {fps:5.1f} fps")

        # Pace to target FPS so the encoder sees the cadence it expects
        next_t = loop_start + count * interval
        sleep = next_t - time.monotonic()
        if sleep > 0:
            time.sleep(sleep)

except KeyboardInterrupt:
    print("\nStopping.")
finally:
    cap.release()
