"""Stream a webcam over Adamo via the native capture path.

The Rust hw_pipeline owns the capture + encoder threads. On Linux it
opens a V4L2 device (/dev/video0); on macOS it opens an AVFoundation
camera (the `device` string is reinterpreted as a camera UID, or "default"
falls through to the default camera). Frames never cross into Python —
the entire capture → encode → Zenoh flow runs in Rust.

Install:
    pip install adamo

Run:
    export ADAMO_API_KEY=ak_...
    python webcam_stream.py                 # default camera
    python webcam_stream.py /dev/video2     # Linux: specific V4L2 device
    python webcam_stream.py <avf-uid>       # macOS: specific AVFoundation UID

Watch the stream on operate.adamohq.com under your participant name.
Ctrl+C to stop.
"""
from __future__ import annotations

import os
import sys

import adamo

API_KEY = os.environ.get("ADAMO_API_KEY") or sys.exit(
    "Set ADAMO_API_KEY=ak_... in your environment"
)

DEVICE = sys.argv[1] if len(sys.argv) > 1 else "default"
PARTICIPANT_NAME = "mac-webcam"
TRACK_NAME = "webcam"
WIDTH, HEIGHT = 1280, 720
FPS = 30
BITRATE_KBPS = 4000

robot = adamo.Robot(api_key=API_KEY, name=PARTICIPANT_NAME, protocol="quic")

# Native capture: Rust owns the device, no Python frame loop. The encoder
# is auto-detected (vtenc_h264 on macOS, nvh264enc/vah264enc on Linux).
robot.attach_video(
    TRACK_NAME,
    device=DEVICE,
    codec="h264",
    width=WIDTH,
    height=HEIGHT,
    fps=FPS,
    bitrate_kbps=BITRATE_KBPS,
)

print(
    f"Streaming device={DEVICE!r} → "
    f"adamo/.../{PARTICIPANT_NAME}/{TRACK_NAME} "
    f"({WIDTH}x{HEIGHT} @ {FPS}fps, {BITRATE_KBPS} kbps)"
)
print("Ctrl+C to stop.")

try:
    robot.run()
except KeyboardInterrupt:
    print("\nStopping.")
finally:
    robot.close()
