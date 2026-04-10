"""Adamo participant session — streams video and data via MoQ.

Thin Python wrapper around the native Rust adamo._native module.
Adds ROS 2 topic support via rclpy (lazy import, not a hard dependency).
"""
from __future__ import annotations

import threading
from typing import Callable
from adamo._native import Robot as _RustRobot, VideoTrack, DataTrack


class Robot:
    """Adamo participant session — bidirectional video, data, and messaging via MoQ.

    Models a single participant on the MoQ network. A participant owns one
    broadcast (named by ``name``) and can:

    * publish video tracks (:meth:`attach_video` / :meth:`video`)
    * publish named data tracks (:meth:`publish`) for low-latency control etc.
    * subscribe to data tracks on other broadcasts (:meth:`subscribe`)
    * send/receive opaque messages via the legacy ``send``/``on_message`` API

    A leader rig (no cameras) uses only :meth:`publish`; a follower robot uses
    :meth:`attach_video` + :meth:`subscribe`; a web-style viewer uses none of
    these (the browser side uses ``@moq/watch``). The same class covers all
    three roles — the role is defined by which methods you call.

    Wraps the native Rust Robot with Python-side ROS 2 support.
    """

    def __init__(
        self,
        api_key: str,
        name: str | None = None,
        relay: str | None = None,
        target: str | None = None,
    ):
        self._rust = _RustRobot(api_key=api_key, name=name, relay=relay, target=target)
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

    def publish(self, name: str, *, priority: int = 200) -> DataTrack:
        """Publish a named data track on this participant's broadcast.

        Returns a :class:`DataTrack` handle. Call ``.put(bytes)`` on the
        handle to send frames. Each ``put()`` creates one MoQ group with
        one frame, giving subscribers latest-wins semantics.

        Priority is a 0-255 scale; higher = more important. Video defaults
        to 1, legacy "data" track to 2. Use ``priority=250`` for control
        commands so they drain ahead of video under congestion.

        Must be called before the runtime starts (before any ``put()`` or
        ``run()``).

        Example — a GELLO leader rig with no cameras::

            p = adamo.Participant(api_key=..., name="gello-01")
            ctl = p.publish("control/joints", priority=250)
            while True:
                ctl.put(encode(read_encoders()))
        """
        return self._rust.publish(name, priority=priority)

    def subscribe(
        self,
        broadcast: str,
        track: str,
        callback: Callable[[bytes], None],
        *,
        priority: int = 200,
    ) -> None:
        """Subscribe to a named track on another participant's broadcast.

        ``broadcast`` is either a short name (``"gello-01"``) resolved
        against the current organisation, or a fully-qualified path
        (``"my-org/gello-01"``).

        ``callback`` is called with each incoming payload as ``bytes`` on
        a dedicated background thread. If the callback blocks, newer
        frames are dropped (latest-wins).

        Must be called before the runtime starts.

        Example — a follower robot consuming leader commands::

            p = adamo.Participant(api_key=..., name="robot-1")
            p.attach_video("front", device="/dev/video0")

            def on_joints(data):
                apply_joints(decode(data))

            p.subscribe("gello-01", "control/joints", on_joints)
            p.run()
        """
        self._rust.subscribe(broadcast, track, callback, priority=priority)

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


# A Participant is just a Robot. The "Robot" name predates the abstraction;
# for leader rigs, trainers, and generic peers, "Participant" reads better.
# Both names point at the same class so existing code keeps working.
Participant = Robot
