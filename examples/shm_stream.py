"""Stream video from iceoryx2 shared memory through Adamo.

Reads frames published by shm_camera_source.py (or a ROS bridge node)
from iceoryx2 shared memory and streams them via the MoQ pipeline.

Usage:
    # Terminal 1: start the camera source
    python shm_camera_source.py

    # Terminal 2: stream to Adamo
    python shm_stream.py
"""

from adamo_video import Robot

API_KEY = "ak_2M3T7rqPYGubJO2gBsxRoWswKn83z0L6"
robot = Robot(api_key=API_KEY, name="mac-test")
robot.attach_video(
    "webcam",
    shm="camera/front",
    width=1280,
    height=720,
    fps=30,
    bitrate_kbps=4000,
)
robot.run()
