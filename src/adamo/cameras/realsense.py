"""Intel RealSense camera adapter (librealsense2 / pyrealsense2).

Use this adapter when you need depth, depth-to-color alignment, IMU, or
factory calibration. For color-only RealSense streaming, the V4L2 adapter
already works (RealSense exposes color as a UVC node).

Install: ``pip install pyrealsense2``.
"""
from __future__ import annotations

import threading
from typing import Optional

from .base import AttachOptions, CameraInfo


def _import_rs():
    try:
        import pyrealsense2 as rs  # type: ignore
    except ImportError as e:
        raise ImportError(
            "pyrealsense2 is not installed. Install with `pip install "
            "pyrealsense2`."
        ) from e
    return rs


def discover() -> list[CameraInfo]:
    try:
        rs = _import_rs()
    except ImportError:
        return []
    out: list[CameraInfo] = []
    ctx = rs.context()
    for dev in ctx.query_devices():
        try:
            name = dev.get_info(rs.camera_info.name)
            serial = dev.get_info(rs.camera_info.serial_number)
        except Exception:
            continue
        # Detect IMU: D435i/D455 expose motion sensors.
        has_imu = any(
            s.is_motion_sensor() for s in dev.query_sensors()
            if hasattr(s, "is_motion_sensor")
        )
        out.append(
            CameraInfo(
                vendor="realsense",
                model=name,
                serial=serial,
                handle=serial,
                has_depth=True,
                has_imu=has_imu,
            )
        )
    return out


class RealSenseCamera:
    """Open a RealSense, publish color (+depth/IMU optionally) to adamo tracks.

    Uses ``rs2.pipeline`` in pull mode (`wait_for_frames`) on a worker
    thread. Depth is published as a 16-bit single-plane stream.
    """

    def __init__(
        self,
        *,
        serial: Optional[str] = None,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        depth: bool = False,
        align_depth_to_color: bool = True,
    ):
        self._rs = _import_rs()
        self._serial = serial
        self._width = width
        self._height = height
        self._fps = fps
        self._depth = depth
        self._align = align_depth_to_color
        self._pipe = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._color_track = None
        self._depth_track = None
        self._calib: Optional[dict] = None

    def open(self) -> None:
        rs = self._rs
        cfg = rs.config()
        if self._serial:
            cfg.enable_device(self._serial)
        cfg.enable_stream(
            rs.stream.color, self._width, self._height, rs.format.bgra8, self._fps
        )
        if self._depth:
            cfg.enable_stream(
                rs.stream.depth, self._width, self._height, rs.format.z16, self._fps
            )
        pipe = rs.pipeline()
        profile = pipe.start(cfg)
        self._pipe = pipe

        # Read intrinsics from the color stream.
        color_stream = profile.get_stream(rs.stream.color).as_video_stream_profile()
        intr = color_stream.get_intrinsics()
        self._calib = {
            "intrinsics": [float(intr.fx), float(intr.fy), float(intr.ppx), float(intr.ppy)],
            "model": str(intr.model),
            "distortion": list(intr.coeffs),
        }

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._pipe is not None:
            self._pipe.stop()
            self._pipe = None

    def attach(
        self,
        robot,
        *,
        name: str = "realsense",
        options: Optional[AttachOptions] = None,
    ) -> None:
        if self._pipe is None:
            self.open()
        opts = options or AttachOptions(prefer_fps=self._fps)
        intr = self._calib["intrinsics"] if self._calib else None
        self._color_track = robot.video(
            name=name,
            width=self._width,
            height=self._height,
            pixel_format="BGRA",
            codec=opts.codec,
            encoder=opts.encoder,
            bitrate_kbps=opts.bitrate_kbps,
            fps=self._fps,
            intrinsics=intr,
        )
        if self._depth:
            self._depth_track = robot.video(
                name=f"{name}_depth",
                width=self._width,
                height=self._height,
                pixel_format="GRAY16",
                codec=opts.codec,
                encoder=opts.encoder,
                bitrate_kbps=opts.bitrate_kbps,
                fps=self._fps,
                intrinsics=intr,
                depth_for=name,
            )
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name=f"adamo-rs-{name}", daemon=True
        )
        self._thread.start()

    def _run_loop(self) -> None:
        rs = self._rs
        align = rs.align(rs.stream.color) if (self._depth and self._align) else None
        import numpy as np
        pipe = self._pipe
        assert pipe is not None
        while not self._stop.is_set():
            try:
                frames = pipe.wait_for_frames(timeout_ms=2000)
            except RuntimeError:
                continue
            if align is not None:
                frames = align.process(frames)
            color = frames.get_color_frame()
            if color and self._color_track is not None:
                arr = np.asarray(color.get_data())
                try:
                    self._color_track.send(arr)
                except Exception:
                    pass
            if self._depth and self._depth_track is not None:
                d = frames.get_depth_frame()
                if d:
                    arr = np.asarray(d.get_data())
                    try:
                        self._depth_track.send(arr)
                    except Exception:
                        pass

    @property
    def calibration(self) -> Optional[dict]:
        return self._calib
