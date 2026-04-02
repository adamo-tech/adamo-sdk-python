"""Bridge Adamo joystick commands to a ROS Joy topic.

Subscribes to joystick commands from the Adamo frontend and republishes
them as sensor_msgs/Joy on a local ROS topic.

Usage:
    ros2 run --prefix 'python3' adamo joystick_to_ros.py

Or standalone:
    python3 joystick_to_ros.py
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Joy
from builtin_interfaces.msg import Time

import adamo
from adamo.operate.control import JoystickCommand, decode_control


class JoystickBridge(Node):
    def __init__(self, robot_id: str, api_key: str, ros_topic: str = "/joy"):
        super().__init__("adamo_joystick_bridge")
        self.pub = self.create_publisher(Joy, ros_topic, 10)
        self.get_logger().info(f"Publishing joystick commands to {ros_topic}")

        self.session = adamo.connect(api_key=api_key)
        self.get_logger().info(f"Connected to Adamo org={self.session.org}")

        self.sub = self.session.subscribe(
            f"{robot_id}/control/joy",
            callback=self._on_message,
        )
        self.get_logger().info(f"Listening for commands on {robot_id}/control/joy")

    def _on_message(self, sample):
        msg = decode_control(sample.payload)
        if not isinstance(msg, JoystickCommand):
            return

        joy = Joy()
        joy.header.stamp = Time(sec=msg.stamp_sec, nanosec=msg.stamp_nanosec)
        joy.header.frame_id = "joy"
        joy.axes = [float(a) for a in msg.axes]
        joy.buttons = list(msg.buttons)
        self.pub.publish(joy)

    def destroy_node(self):
        self.sub.close()
        self.session.close()
        super().destroy_node()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Bridge Adamo joystick to ROS")
    parser.add_argument("--robot", required=True, help="Robot ID to listen for")
    parser.add_argument("--api-key", required=True, help="Adamo API key (ak_...)")
    parser.add_argument("--topic", default="/joy", help="ROS topic to publish on")
    args = parser.parse_args()

    rclpy.init()
    node = JoystickBridge(args.robot, args.api_key, args.topic)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
