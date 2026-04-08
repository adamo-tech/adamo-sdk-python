"""Adamo robot session — streams video and data via MoQ.

Thin Python wrapper around the native Rust adamo_video module.
Adds ROS 2 topic support via rclpy (lazy import, not a hard dependency).
"""

import threading
from adamo_video import Robot as _RustRobot, VideoTrack


class Robot:
    """Adamo robot session — bidirectional video, data, and messaging via MoQ.

    Wraps the native Rust Robot with Python-side ROS 2 support.
    """

    def __init__(self, api_key: str, name: str | None = None, relay: str | None = None):
        self._rust = _RustRobot(api_key=api_key, name=name, relay=relay)
        self._ros_threads: list[threading.Thread] = []

    def attach_video(
        self,
        name: str,
        *,
        device: str | None = None,
        shm: str | None = None,
        ros: str | None = None,
        codec: str = "h264",
        bitrate_kbps: int = 2000,
        fps: int = 30,
        width: int = 1280,
        height: int = 720,
    ) -> None:
        if ros is not None:
            self._attach_ros(name, ros, codec, bitrate_kbps, fps, width, height)
        else:
            self._rust.attach_video(
                name,
                device=device,
                shm=shm,
                codec=codec,
                bitrate_kbps=bitrate_kbps,
                fps=fps,
                width=width,
                height=height,
            )

    def _attach_ros(
        self, name: str, topic: str, codec: str, bitrate_kbps: int, fps: int, width: int, height: int
    ) -> None:
        try:
            import rclpy
            from sensor_msgs.msg import Image
        except ImportError:
            raise ImportError(
                "rclpy is required for ros= sources. "
                "Install ROS 2 and source your workspace, or: pip install rclpy sensor_msgs"
            )

        # Detect pixel format from first message to pick the right format
        # Default to BGRA which VideoToolbox/NVENC prefer
        track = self._rust.video(
            name,
            width=width,
            height=height,
            pixel_format="BGRA",
            codec=codec,
            bitrate_kbps=bitrate_kbps,
            fps=fps,
        )

        def ros_spin():
            rclpy.init()
            from rclpy.node import Node

            node = Node(f"adamo_bridge_{name}")

            # Map ROS encoding → expected pixel format + conversion
            encoding_map = {
                "bgra8": None,         # already BGRA, no conversion
                "rgba8": None,         # close enough for most encoders
                "bgr8": "BGR2BGRA",
                "rgb8": "RGB2BGRA",
                "mono8": "GRAY2BGRA",
            }

            def on_image(msg: Image):
                import numpy as np
                import cv2

                h, w = msg.height, msg.width
                enc = msg.encoding.lower()

                conversion = encoding_map.get(enc)
                if conversion is None and enc not in encoding_map:
                    node.get_logger().warn(f"Unsupported encoding '{msg.encoding}', skipping")
                    return

                data = np.frombuffer(msg.data, dtype=np.uint8)

                if enc == "bgra8" or enc == "rgba8":
                    frame = data.reshape((h, w, 4))
                elif enc in ("bgr8", "rgb8"):
                    frame = data.reshape((h, w, 3))
                    frame = cv2.cvtColor(frame, getattr(cv2, f"COLOR_{conversion}"))
                elif enc == "mono8":
                    frame = data.reshape((h, w))
                    frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGRA)
                else:
                    return

                frame = np.ascontiguousarray(frame)
                track.send(frame)

            node.create_subscription(Image, topic, on_image, 2)
            node.get_logger().info(f"Bridging '{topic}' → adamo track '{name}'")

            try:
                rclpy.spin(node)
            except Exception:
                pass
            finally:
                node.destroy_node()
                rclpy.shutdown()

        t = threading.Thread(target=ros_spin, name=f"ros-{name}", daemon=True)
        t.start()
        self._ros_threads.append(t)

    def video(self, name: str, **kwargs) -> VideoTrack:
        return self._rust.video(name, **kwargs)

    def send(self, channel: str, data) -> None:
        """Send data to viewers on a named channel."""
        self._rust.send(channel, data)

    def recv(self) -> tuple[str, bytes]:
        """Block until a message arrives from a viewer. Returns (channel, data)."""
        return self._rust.recv()

    def on_message(self, callback) -> None:
        """Register a callback for incoming messages: callback(channel: str, data: bytes).

        Can be used as a decorator::

            @robot.on_message
            def handle(channel, data):
                if channel == "teleop":
                    cmd = json.loads(data)
        """
        self._rust.on_message(callback)
        return callback

    def run(self) -> None:
        """Block until the session ends."""
        self._rust.run()
