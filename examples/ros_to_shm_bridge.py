"""ROS 2 → iceoryx2 bridge — subscribes to a ROS Image topic and writes to shared memory.

This bridges ROS 2 camera data into iceoryx2 so the Adamo SDK can pick it up
for hardware encoding and MoQ streaming.

Wire format matches what shm_push.rs expects:
  [timestamp_us: u64 LE][raw pixel data]

Usage:
    # Terminal 1: ROS 2 camera publisher (or any node publishing sensor_msgs/Image)
    python ros_camera_source.py

    # Terminal 2: this bridge
    python ros_to_shm_bridge.py

    # Terminal 3: Adamo SDK streaming
    python shm_stream.py
"""

import ctypes
import struct
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
import iceoryx2 as iox2


ROS_TOPIC = "/camera/image_raw"
SHM_SERVICE = "camera/front"


class RosToShmBridge(Node):
    def __init__(self):
        super().__init__("ros_to_shm_bridge")

        # iceoryx2 publisher (created lazily on first frame to know the size)
        self.iox_node = iox2.NodeBuilder.new().create(iox2.ServiceType.Ipc)
        self.iox_pub = None
        self.payload_size = 0

        self.subscription = self.create_subscription(
            Image, ROS_TOPIC, self.on_image, 2
        )

        self.frame_count = 0
        self.start_time = time.monotonic()
        self.get_logger().info(
            f"Bridging '{ROS_TOPIC}' → iceoryx2 '{SHM_SERVICE}'"
        )

    def _ensure_publisher(self, data_size: int):
        """Create iceoryx2 publisher on first frame (now we know the size)."""
        needed = 8 + data_size  # timestamp header + pixel data
        if self.iox_pub is not None and needed <= self.payload_size:
            return
        self.payload_size = needed
        svc = (
            self.iox_node.service_builder(iox2.ServiceName.new(SHM_SERVICE))
            .publish_subscribe(iox2.Slice[ctypes.c_uint8])
            .enable_safe_overflow(True)
            .subscriber_max_buffer_size(2)
            .open_or_create()
        )
        self.iox_pub = (
            svc.publisher_builder()
            .initial_max_slice_len(self.payload_size)
            .create()
        )
        self.get_logger().info(
            f"iceoryx2 publisher created: {SHM_SERVICE} ({self.payload_size} bytes)"
        )

    def on_image(self, msg: Image):
        data = bytes(msg.data)
        self._ensure_publisher(len(data))

        # Build payload: [timestamp_us: u64 LE][pixel data]
        stamp = msg.header.stamp
        timestamp_us = stamp.sec * 1_000_000 + stamp.nanosec // 1000
        header = struct.pack("<Q", timestamp_us)
        payload = header + data

        sample = self.iox_pub.loan_slice_uninit(len(payload))
        ctypes.memmove(sample.payload_ptr, payload, len(payload))
        sample.assume_init().send()

        self.frame_count += 1
        if self.frame_count % 150 == 0:
            elapsed = time.monotonic() - self.start_time
            fps = self.frame_count / elapsed
            self.get_logger().info(
                f"{self.frame_count} frames bridged | {fps:.1f} fps | "
                f"{msg.width}x{msg.height} {msg.encoding}"
            )


def main():
    rclpy.init()
    node = RosToShmBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
