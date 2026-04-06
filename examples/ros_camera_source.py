"""ROS 2 camera source — publishes webcam frames as sensor_msgs/Image.

Run this alongside ros_to_shm_bridge.py to test the full pipeline:
  ROS 2 Image topic → iceoryx2 shared memory → Adamo SDK → MoQ relay

Usage:
    # Terminal 1: ROS 2 camera publisher
    python ros_camera_source.py

    # Terminal 2: bridge ROS → iceoryx2
    python ros_to_shm_bridge.py

    # Terminal 3: stream to Adamo
    python shm_stream.py
"""

import cv2
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image


TOPIC = "/camera/image_raw"
WIDTH = 1280
HEIGHT = 720
FPS = 30
CAMERA_INDEX = 0


class CameraPublisher(Node):
    def __init__(self):
        super().__init__("camera_publisher")
        self.publisher = self.create_publisher(Image, TOPIC, 2)
        self.timer = self.create_timer(1.0 / FPS, self.publish_frame)
        self.cap = cv2.VideoCapture(CAMERA_INDEX)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        self.frame_count = 0

        if not self.cap.isOpened():
            self.get_logger().error(f"Failed to open camera {CAMERA_INDEX}")
            raise RuntimeError("Camera not available")

        self.get_logger().info(
            f"Publishing {WIDTH}x{HEIGHT} BGRA @{FPS}fps to '{TOPIC}'"
        )

    def publish_frame(self):
        ret, frame = self.cap.read()
        if not ret:
            self.get_logger().warn("Camera read failed")
            return

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)

        msg = Image()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "camera"
        msg.height = frame.shape[0]
        msg.width = frame.shape[1]
        msg.encoding = "bgra8"
        msg.is_bigendian = 0
        msg.step = frame.shape[1] * 4
        msg.data = frame.tobytes()

        self.publisher.publish(msg)
        self.frame_count += 1

        if self.frame_count % (FPS * 5) == 0:
            self.get_logger().info(f"{self.frame_count} frames published")

    def destroy_node(self):
        self.cap.release()
        super().destroy_node()


def main():
    rclpy.init()
    node = CameraPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
