"""Adamo participant session — streams video and data via Zenoh.

Combines the Rust native extension (video capture + hardware encoding) with
the pure-Python eclipse-zenoh client (pub/sub, liveliness, queries) into one
unified participant API.

A leader rig with no cameras uses only :meth:`publish` / :meth:`subscribe`;
a follower robot uses :meth:`attach_video` + :meth:`subscribe`; a Python
perception pipeline uses :meth:`video` + ``track.send(frame)``. The same
class covers all three roles — the role is defined by which methods you
call.
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Callable

from adamo._native import Robot as _RustRobot, detect_encoder

if TYPE_CHECKING:
    from adamo._video import VideoTrack as _VideoTrackType
    from adamo._auth import ConnectionInfo
    from adamo.operate.session import Session, Sample


_H264_ENCODER_HINTS = (
    "nvv4l2h264enc",
    "nvh264enc",
    "vah264enc",
    "vtenc_h264",
)
_H265_ENCODER_HINTS = (
    "nvv4l2h265enc",
    "nvh265enc",
)
_AV1_ENCODER_HINTS = (
    "nvv4l2av1enc",
    "nvav1enc",
)


def _compile_track_pattern(track: str) -> tuple[str, list[str]]:
    """Convert ``control/xr/{side}`` → (``control/xr/*``, [``"side"``]).

    Returns the Zenoh-subscribable track key plus the ordered list of
    named captures. Raw Zenoh wildcards (``*``, ``**``) are passed through
    unchanged and contribute no capture name.
    """
    segments: list[str] = []
    captures: list[str] = []
    for seg in track.split("/"):
        if seg.startswith("{") and seg.endswith("}") and len(seg) > 2:
            captures.append(seg[1:-1])
            segments.append("*")
        else:
            segments.append(seg)
    return "/".join(segments), captures


def _resolve_encoder(codec: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    detected = detect_encoder()
    codec = codec.lower()
    if codec == "h264":
        if detected in _H264_ENCODER_HINTS:
            return detected
        # fallback: detect_encoder already returns the best available h264
        return detected if detected != "none" else "vtenc_h264"
    if codec in ("h265", "hevc"):
        # detect_encoder returns h264 only; require explicit for other codecs
        raise ValueError(
            "h265/hevc requires explicit encoder= kwarg (e.g. 'nvh265enc')"
        )
    if codec == "av1":
        raise ValueError(
            "av1 requires explicit encoder= kwarg (e.g. 'nvav1enc')"
        )
    raise ValueError(f"Unknown codec '{codec}' (supported: h264, h265, av1)")


class Robot:
    """Adamo participant — video, data, control, and messaging via Zenoh.

    Parameters
    ----------
    api_key:
        Adamo API key (``ak_...``). Fetches org-scoped Zenoh endpoints from
        the Adamo API.
    name:
        Short robot/participant name.
    relay:
        Override the Zenoh router endpoint. When omitted, the best router
        for your org is chosen by the Adamo API.
    protocol:
        ``"quic"`` (default), ``"udp"``, or ``"tcp"``.
    """

    def __init__(
        self,
        api_key: str | None = None,
        name: str | None = None,
        relay: str | None = None,
        protocol: str = "quic",
    ):
        self._api_key = api_key
        self._name = name
        self._relay = relay
        self._protocol = protocol
        self._rust = _RustRobot(
            api_key=api_key,
            name=name,
            router=relay,
            protocol=protocol,
        )
        self._ros_threads: list[threading.Thread] = []
        self._video_tracks: list = []  # holds VideoTrack instances to keep publishers alive
        self._attached_count = 0  # bumped by attach_video (no Python handle)
        self._session: "Session | None" = None
        self._session_lock = threading.Lock()
        self._publishers: dict = {}
        self._subscribers: list = []
        self._messages_sub = None
        self._msg_queue: list[tuple[str, bytes]] = []
        self._msg_cond = threading.Condition()
        self._msg_channel_prefix = "msg"
        self._on_message_cbs: list[Callable[[str, bytes], None]] = []
        self._run_called = False
        self._pipeline_thread: threading.Thread | None = None
        self._pipeline_lock = threading.Lock()

    # -- Lazy Zenoh session -----------------------------------------------------

    def _zenoh(self) -> "Session":
        """Open (once) and return the underlying Zenoh session."""
        if self._session is not None:
            return self._session
        with self._session_lock:
            if self._session is not None:
                return self._session
            from adamo.operate import connect

            if self._api_key is None:
                raise RuntimeError(
                    "Cannot open Zenoh session without an API key"
                )
            self._session = connect(
                api_key=self._api_key, protocol=self._protocol
            )
            return self._session

    @property
    def session(self) -> "Session":
        """The underlying Zenoh :class:`adamo.operate.Session` (opens on first access)."""
        return self._zenoh()

    # -- Video ------------------------------------------------------------------

    def attach_video(
        self,
        name: str,
        *,
        device: str | int | None = None,
        shm: str | None = None,
        ros: str | None = None,
        pipeline: str | None = None,
        codec: str = "h264",
        encoder: str | None = None,
        bitrate_kbps: int = 2000,
        fps: int = 30,
        width: int = 1280,
        height: int = 720,
        pixel_format: str | None = None,
        keyframe_distance: float = 2.0,
    ) -> None:
        """Attach a video track driven by the Rust pipeline.

        Exactly one of ``device`` / ``shm`` / ``ros`` / ``pipeline`` must be
        provided. The Rust side owns the capture and encoder thread; frames
        never cross into Python.

        For a Python-driven frame loop, use :meth:`video` instead.
        """
        sources = [s for s in (device, shm, ros, pipeline) if s is not None]
        if len(sources) != 1:
            raise ValueError(
                "attach_video: pass exactly one of device=, shm=, ros=, pipeline="
            )

        enc = _resolve_encoder(codec, encoder)

        if ros is not None:
            self._attach_ros(name, ros, enc, bitrate_kbps, fps, width, height)
            return

        kwargs: dict = dict(
            encoder=enc,
            bitrate=bitrate_kbps,
            fps=fps,
            keyframe_distance=keyframe_distance,
        )
        if pixel_format is not None:
            kwargs["source_format"] = pixel_format

        if device is not None:
            kwargs["source_type"] = "v4l2"
            kwargs["v4l2_device"] = str(device)
            kwargs["v4l2_capture_resolution"] = [width, height]
        elif shm is not None:
            kwargs["source_type"] = "shm"
            kwargs["shm_service"] = shm
            kwargs["v4l2_capture_resolution"] = [width, height]
            if pixel_format is None:
                kwargs["source_format"] = "BGRA"
        elif pipeline is not None:
            kwargs["source_type"] = "gstreamer"
            kwargs["gstreamer_pipeline"] = pipeline

        self._rust.video(name, **kwargs)
        self._attached_count += 1

    def video(
        self,
        name: str,
        *,
        width: int = 1280,
        height: int = 720,
        pixel_format: str = "BGRA",
        codec: str = "h264",
        encoder: str | None = None,
        bitrate_kbps: int = 2000,
        fps: int = 30,
        keyframe_distance: float = 2.0,
    ) -> "_VideoTrackType":
        """Create a Python-driven video track. Returns a :class:`VideoTrack`.

        Call ``track.send(frame)`` with numpy arrays (or bytes) to push
        frames. Frames travel through iceoryx2 shared memory → the Rust
        encoder → Zenoh.

        Requires ``iceoryx2`` (``pip install 'adamo[video]'``).
        """
        from adamo._video import VideoTrack, allocate_service_name

        service = allocate_service_name(name)
        track = VideoTrack(
            name=name,
            width=width,
            height=height,
            pixel_format=pixel_format,
            service_name=service,
        )
        enc = _resolve_encoder(codec, encoder)
        self._rust.video(
            name,
            encoder=enc,
            source_type="shm",
            shm_service=service,
            v4l2_capture_resolution=[width, height],
            source_format=pixel_format,
            bitrate=bitrate_kbps,
            fps=fps,
            keyframe_distance=keyframe_distance,
        )
        # Hook auto-start: first frame pushed will spin up the Rust pipeline
        # in a background thread if the user hasn't called run() yet.
        track._on_first_send = self._start_pipeline_background  # type: ignore[attr-defined]
        self._video_tracks.append(track)
        return track

    def _start_pipeline_background(self) -> None:
        """Start the Rust video pipeline in a daemon thread (idempotent).

        Called lazily from :meth:`VideoTrack.send` when the user's control
        flow is a Python frame loop rather than ``robot.run()``.
        """
        with self._pipeline_lock:
            if self._pipeline_thread is not None or self._run_called:
                return

            def _run():
                try:
                    self._rust.run()
                except Exception:
                    pass

            t = threading.Thread(target=_run, name="adamo-pipeline", daemon=True)
            t.start()
            self._pipeline_thread = t

    def _attach_ros(
        self,
        name: str,
        topic: str,
        encoder: str,
        bitrate_kbps: int,
        fps: int,
        width: int,
        height: int,
    ) -> None:
        """Bridge a ROS 2 sensor_msgs/Image topic via rclpy → iceoryx2 → Rust.

        Uses the Python-driven video path internally so we don't depend on
        the Rust ROS source (which requires a zenoh-ros2dds bridge).
        """
        try:
            import rclpy
            from sensor_msgs.msg import Image
        except ImportError as e:
            raise ImportError(
                "rclpy is required for ros= sources. "
                "Install ROS 2 and source your workspace, or: "
                "pip install rclpy sensor_msgs"
            ) from e

        track = self.video(
            name,
            width=width,
            height=height,
            pixel_format="BGRA",
            encoder=encoder,
            bitrate_kbps=bitrate_kbps,
            fps=fps,
        )

        def ros_spin():
            import numpy as np
            import cv2

            rclpy.init()
            from rclpy.node import Node

            node = Node(f"adamo_bridge_{name}")

            encoding_map = {
                "bgra8": None,
                "rgba8": None,
                "bgr8": "BGR2BGRA",
                "rgb8": "RGB2BGRA",
                "mono8": "GRAY2BGRA",
            }

            def on_image(msg: "Image"):
                h, w = msg.height, msg.width
                enc = msg.encoding.lower()

                conversion = encoding_map.get(enc)
                if conversion is None and enc not in encoding_map:
                    node.get_logger().warn(
                        f"Unsupported encoding '{msg.encoding}', skipping"
                    )
                    return

                data = np.frombuffer(msg.data, dtype=np.uint8)

                if enc in ("bgra8", "rgba8"):
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
            node.get_logger().info(
                f"Bridging '{topic}' → adamo track '{name}'"
            )

            try:
                rclpy.spin(node)
            except Exception:
                pass
            finally:
                node.destroy_node()
                rclpy.shutdown()

        t = threading.Thread(
            target=ros_spin, name=f"ros-{name}", daemon=True
        )
        t.start()
        self._ros_threads.append(t)

    # -- Data / control via Zenoh ----------------------------------------------

    def publish(
        self,
        track: str,
        *,
        priority: int = 200,
        express: bool = False,
        reliable: bool = False,
    ) -> "Publisher":
        """Declare a publisher for a named track under this participant.

        ``priority`` is a 0-255 scale (higher = more important) and is
        mapped to one of zenoh's 8 priority classes in Rust. Use
        ``priority=250`` for control commands so they drain ahead of
        video under congestion.
        """
        full_key = self._scoped_key(track)
        pub = self.session.publisher(
            full_key,
            raw=True,
            priority=priority,
            express=express,
            reliable=reliable,
        )
        self._publishers[full_key] = pub
        return pub

    def subscribe(
        self,
        broadcast: str,
        track: str | list[str],
        callback: Callable[..., None],
        *,
        priority: int = 200,  # accepted for API symmetry; Zenoh doesn't use sub priority
    ) -> Callable[..., None]:
        """Subscribe to one or more tracks on another participant's broadcast.

        ``broadcast`` is a short participant name (resolved against the
        current org) or a fully-qualified ``{org}/{name}`` path. ``track``
        may be a single key (with Zenoh wildcards ``*`` / ``**`` allowed,
        or ``{name}`` placeholders that capture a segment by name), or a
        list of such keys. The callback fires on the Zenoh receiver thread.

        Named captures in the pattern (e.g. ``control/xr/{side}``) are
        passed to the callback as keyword arguments matching parameter names.
        Returns the callback unchanged so this can also be used as a decorator.
        """
        import inspect

        tracks = [track] if isinstance(track, str) else list(track)
        try:
            sig_params = inspect.signature(callback).parameters
            param_names = {
                name for name, p in sig_params.items()
                if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
            }
            has_var_keyword = any(
                p.kind == p.VAR_KEYWORD for p in sig_params.values()
            )
        except (TypeError, ValueError):
            param_names = set()
            has_var_keyword = False

        for tr in tracks:
            zenoh_track, capture_names = _compile_track_pattern(tr)
            key = self._broadcast_key(broadcast, zenoh_track)

            wanted = [n for n in capture_names if has_var_keyword or n in param_names]

            def _handler(
                sample,
                _cb=callback,
                _captures=capture_names,
                _wanted=wanted,
            ):
                # sample is adamo.operate.Sample
                payload = sample.payload
                if not _wanted:
                    _cb(payload)
                    return
                segs = sample.key.split("/")
                kwargs = {
                    name: segs[-len(_captures) + i]
                    for i, name in enumerate(_captures)
                    if name in _wanted
                }
                _cb(payload, **kwargs)

            sub = self.session.subscribe(key, raw=True, callback=_handler)
            self._subscribers.append(sub)
        return callback

    def on(
        self,
        broadcast: str,
        track: str | list[str],
        *,
        priority: int = 200,
        decode: Callable[[bytes], object] | str | None = "json",
    ) -> Callable[[Callable], Callable]:
        """Decorator: register a handler for one or more tracks.

        ``track`` may include Zenoh wildcards (``*``, ``**``) or be a list
        of keys. If the decorated function accepts two positional params,
        the second is the matched key expression.

        ``decode`` controls how the raw payload is transformed before the
        handler is called:
          * ``"json"`` (default) — ``json.loads(payload)``
          * ``"control"`` — :func:`adamo.operate.control.decode_control`
          * ``None`` — pass raw ``bytes``
          * a callable — called with raw ``bytes``, its return value is passed in
        """
        import inspect
        import json as _json

        if decode == "json":
            _decode = _json.loads
        elif decode == "control":
            from adamo.operate.control import decode_control as _decode
        elif decode is None:
            _decode = lambda b: b  # noqa: E731
        elif callable(decode):
            _decode = decode
        else:
            raise ValueError(f"Unknown decode mode: {decode!r}")

        def _wrap(fn: Callable) -> Callable:
            def _cb(payload: bytes, **kwargs) -> None:
                fn(_decode(payload), **kwargs)

            # Preserve fn's signature so subscribe() can inspect capture names.
            try:
                _cb.__signature__ = inspect.signature(fn)  # type: ignore[attr-defined]
            except (TypeError, ValueError):
                pass
            self.subscribe(broadcast, track, _cb, priority=priority)
            return fn

        return _wrap

    # -- Logging ----------------------------------------------------------------

    def log(self, message: str, *, level: str = "info") -> None:
        """Publish a log line from this robot.

        The payload is a single-line JSON object ``{"ts_us", "level",
        "message"}`` using fabric time (synchronised with every other
        node on the network). Frontends subscribe to this stream and
        render the logs in their console.
        """
        import json as _json

        from adamo._native import fabric_now_us

        text = str(message)
        if len(text) > 10_000:
            text = text[:10_000] + "... [truncated]"
        payload = _json.dumps(
            {
                "ts_us": fabric_now_us(),
                "level": str(level).lower(),
                "message": text,
            },
            separators=(",", ":"),
        ).encode()
        from adamo.operate.session import Priority

        key = f"{self._name}/logs"
        pub = self._publishers.get(key)
        if pub is None:
            pub = self.session.publisher(
                key,
                priority=Priority.REAL_TIME,
                express=True,
                reliable=False,
            )
            self._publishers[key] = pub
        pub.put(payload)

    # -- Viewer messaging (send/recv/on_message) -------------------------------

    def send(self, channel: str, data: bytes | str) -> None:
        """Send a message to a named channel on this participant's broadcast."""
        if isinstance(data, str):
            data = data.encode()
        key = self._scoped_key(f"{self._msg_channel_prefix}/{channel}")
        self.session.put(key, data, raw=True)

    def recv(self, timeout: float | None = None) -> tuple[str, bytes]:
        """Block until a message arrives from any viewer. Returns (channel, data)."""
        self._ensure_message_subscriber()
        with self._msg_cond:
            deadline = None if timeout is None else time.monotonic() + timeout
            while not self._msg_queue:
                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                if remaining == 0.0:
                    raise TimeoutError("recv() timed out")
                self._msg_cond.wait(remaining)
            return self._msg_queue.pop(0)

    def on_message(self, callback: Callable[[str, bytes], None]) -> Callable:
        """Register a callback for incoming messages: ``callback(channel, data)``.

        Can be used as a decorator.
        """
        self._on_message_cbs.append(callback)
        self._ensure_message_subscriber()
        return callback

    def _ensure_message_subscriber(self) -> None:
        if self._messages_sub is not None:
            return
        session = self.session
        full_prefix = self._scoped_key(f"{self._msg_channel_prefix}/")
        key = f"{full_prefix}**"
        short_prefix = f"{self._name}/{self._msg_channel_prefix}/"

        def _handler(sample):
            stripped = sample.key
            if stripped.startswith(short_prefix):
                channel = stripped[len(short_prefix):]
            else:
                channel = stripped
            payload = sample.payload
            with self._msg_cond:
                self._msg_queue.append((channel, payload))
                self._msg_cond.notify()
            for cb in list(self._on_message_cbs):
                try:
                    cb(channel, payload)
                except Exception:
                    pass

        self._messages_sub = session.subscribe(key, raw=True, callback=_handler)

    # -- Keyspace helpers ------------------------------------------------------

    def _scoped_key(self, suffix: str) -> str:
        if not self._name:
            raise RuntimeError(
                "Robot needs a name= to declare scoped keys"
            )
        return f"{self.session._prefix}{self._name}/{suffix}"

    def _broadcast_key(self, broadcast: str, track: str) -> str:
        if "/" in broadcast:
            return f"adamo/{broadcast}/{track}"
        return f"{self.session._prefix}{broadcast}/{track}"

    # -- Lifecycle -------------------------------------------------------------

    def run(self) -> None:
        """Block until the session ends.

        If any video tracks were attached, runs the Rust pipeline (which
        blocks). Otherwise blocks waiting for Ctrl+C — useful for leader
        rigs that only publish control data.
        """
        self._run_called = True
        # Ensure Zenoh session is up so late publishers/subs declared from
        # other threads don't race against the block below.
        self._zenoh()

        if self._has_video_tracks():
            self._rust.run()
        else:
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                pass

    def _has_video_tracks(self) -> bool:
        return bool(self._video_tracks) or self._attached_count > 0

    def close(self) -> None:
        for sub in self._subscribers:
            try:
                sub.close()
            except Exception:
                pass
        self._subscribers.clear()
        if self._messages_sub is not None:
            try:
                self._messages_sub.close()
            except Exception:
                pass
            self._messages_sub = None
        for pub in self._publishers.values():
            try:
                pub.close()
            except Exception:
                pass
        self._publishers.clear()
        for track in self._video_tracks:
            try:
                track.close()
            except Exception:
                pass
        self._video_tracks.clear()
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# A Participant is just a Robot — "Participant" reads better for leader rigs
# and trainers that have no cameras. The 0-255 priority scale is mapped into
# zenoh's 8 priority classes by `priority_from_u8` on the Rust side.
Participant = Robot
