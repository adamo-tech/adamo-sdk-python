"""Stream a ROS 2 camera topic through Adamo.

Subscribes to a sensor_msgs/Image topic via rclpy and streams it
through the hardware encoder and MoQ transport.

Requires: ROS 2 + rclpy + sensor_msgs (source your workspace first)

Usage:
    python stream_ros.py
"""

from adamo.video import Robot

API_KEY = "ak_2M3T7rqPYGubJO2gBsxRoWswKn83z0L6"

robot = Robot(api_key=API_KEY, name="jetson-test")
robot.attach_video(
    "front",
    ros="/camera/image_raw",
    width=1280,
    height=720,
    bitrate_kbps=4000,
    fps=30,
)
robot.run()
