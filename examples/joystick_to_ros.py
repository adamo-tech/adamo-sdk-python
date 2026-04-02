"""Bridge Adamo joystick commands to a ROS Joy topic."""

import argparse
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Joy
import adamo
from adamo.operate.control import JoystickCommand, decode_control

class JoystickBridge(Node):
    def __init__(self, robot_id, api_key, topic="/adamo/joy"):
        super().__init__("adamo_joystick_bridge")
        self.pub = self.create_publisher(Joy, topic, 10)
        self.session = adamo.connect(api_key=api_key)
        self.session.subscribe(f"{robot_id}/control/joy", callback=self._on_msg)

    def _on_msg(self, sample):
        msg = decode_control(sample.payload)
        if isinstance(msg, JoystickCommand):
            joy = Joy()
            joy.header.stamp.sec = int(msg.stamp)
            joy.header.stamp.nanosec = int((msg.stamp % 1) * 1e9)
            joy.axes = [float(a) for a in msg.axes]
            joy.buttons = list(msg.buttons)
            self.pub.publish(joy)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--robot", required=True)
    p.add_argument("--api-key", required=True)
    p.add_argument("--topic", default="/adamo/joy")
    args = p.parse_args()
    rclpy.init()
    rclpy.spin(JoystickBridge(args.robot, args.api_key, args.topic))
