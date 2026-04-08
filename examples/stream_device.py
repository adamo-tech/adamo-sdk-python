"""Test 1: Device capture — SDK owns the camera.

The Rust code captures directly from the specified device via AVFoundation,
encodes with VideoToolbox, and publishes over MoQ. No Python frame loop.

Usage:
    python stream_device.py
"""

from adamo import Robot

API_KEY = "ak_2M3T7rqPYGubJO2gBsxRoWswKn83z0L6"

robot = Robot(api_key=API_KEY, name="mac-test")
robot.attach_video(
    "webcam",
    device="0",
    width=1280,
    height=720,
    fps=30,
    bitrate_kbps=4000,
)
robot.run()
