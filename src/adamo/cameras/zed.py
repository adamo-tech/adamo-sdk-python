"""Stereolabs ZED camera adapter.

Uses ``pyzed.sl`` to access factory calibration, depth, and IMU streams that
the V4L2 path can't provide. The color stream itself is also reachable via
plain V4L2 — use this adapter only when you need depth, IMU, or calibration
metadata, since the ZED SDK requires an NVIDIA GPU at runtime.

Install: ``pip install pyzed`` *and* the Stereolabs SDK + matching CUDA
runtime (https://www.stereolabs.com/developers/release/).
"""
from __future__ import annotations

import threading
from typing import Optional

from .base import AttachOptions, CameraInfo


def _import_sl():
    try:
        import pyzed.sl as sl  # type: ignore
    except ImportError as e:
        raise ImportError(
            "pyzed is not installed. The ZED SDK requires NVIDIA + CUDA at "
            "runtime. See https://www.stereolabs.com/developers/release/ "
            "for the SDK, then `pip install pyzed`."
        ) from e
    return sl


def discover() -> list[CameraInfo]:
    """List ZED cameras visible to the SDK.

    Returns an empty list if pyzed isn't installed (so this is safe to call
    on hosts without the SDK).
    """
    try:
        sl = _import_sl()
    except ImportError:
        return []
    out: list[CameraInfo] = []
    devs = sl.Camera.get_device_list()
    for d in devs:
        out.append(
            CameraInfo(
                vendor="zed",
                model=str(getattr(d, "camera_model", "ZED")),
                serial=str(getattr(d, "serial_number", "")),
                handle=str(getattr(d, "serial_number", "")),
                has_depth=True,
                has_imu=True,
                extra={
                    "sdk_path": getattr(d, "path", ""),
                    "id": getattr(d, "id", -1),
                },
            )
        )
    return out


class ZedCamera:
    """Open a ZED, publish color (and optionally depth) into adamo tracks.

    Threading model: a background daemon thread pulls frames from the SDK
    and feeds them into one or more `adamo.VideoTrack` handles obtained via
    ``robot.video(...)``. Calibration is read once at open and injected
    into the color track's intrinsics/extrinsics.
    """

    def __init__(
        self,
        *,
        serial: Optional[int] = None,
        resolution: str = "HD720",  # HD2K | HD1080 | HD720 | VGA
        fps: int = 60,
        depth: bool = False,
    ):
        self._sl = _import_sl()
        self._serial = serial
        self._resolution = resolution
        self._fps = fps
        self._depth = depth
        self._cam = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._color_track = None
        self._depth_track = None
        self._calib = None

    def open(self) -> None:
        sl = self._sl
        params = sl.InitParameters()
        params.camera_resolution = getattr(sl.RESOLUTION, self._resolution)
        params.camera_fps = self._fps
        if self._depth:
            params.depth_mode = sl.DEPTH_MODE.NEURAL
            params.coordinate_units = sl.UNIT.METER
        else:
            params.depth_mode = sl.DEPTH_MODE.NONE
        if self._serial is not None:
            params.set_from_serial_number(int(self._serial))
        cam = sl.Camera()
        status = cam.open(params)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"ZED open failed: {status}")
        self._cam = cam
        info = cam.get_camera_information()
        # Left-eye intrinsics for the color track.
        cam_params = info.camera_configuration.calibration_parameters.left_cam
        self._calib = {
            "intrinsics": [
                float(cam_params.fx),
                float(cam_params.fy),
                float(cam_params.cx),
                float(cam_params.cy),
            ],
            "baseline_m": float(
                info.camera_configuration.calibration_parameters.get_camera_baseline()
            ),
            "model": str(info.camera_model),
            "serial": int(info.serial_number),
        }

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._cam is not None:
            self._cam.close()
            self._cam = None

    def attach(
        self,
        robot,
        *,
        name: str = "zed",
        options: Optional[AttachOptions] = None,
    ) -> None:
        """Create adamo video tracks and start the capture worker."""
        if self._cam is None:
            self.open()
        sl = self._sl
        opts = options or AttachOptions(prefer_fps=self._fps)
        info = self._cam.get_camera_information()
        res = info.camera_configuration.resolution
        width, height = int(res.width), int(res.height)

        intr = self._calib["intrinsics"] if self._calib else None
        # Color track. ZED SDK gives BGRA; we publish that directly.
        self._color_track = robot.video(
            name=name,
            width=width,
            height=height,
            pixel_format="BGRA",
            codec=opts.codec,
            encoder=opts.encoder,
            bitrate_kbps=opts.bitrate_kbps,
            fps=self._fps,
            intrinsics=intr,
        )

        if self._depth:
            # Publish depth as a 16-bit gray track (millimeters → uint16).
            self._depth_track = robot.video(
                name=f"{name}_depth",
                width=width,
                height=height,
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
            target=self._run_loop, name=f"adamo-zed-{name}", daemon=True
        )
        self._thread.start()

    def _run_loop(self) -> None:
        sl = self._sl
        rt = sl.RuntimeParameters()
        image = sl.Mat()
        depth = sl.Mat() if self._depth else None
        cam = self._cam
        assert cam is not None
        while not self._stop.is_set():
            if cam.grab(rt) != sl.ERROR_CODE.SUCCESS:
                continue
            cam.retrieve_image(image, sl.VIEW.LEFT)
            color = image.get_data()  # BGRA numpy view
            if self._color_track is not None:
                try:
                    self._color_track.send(color)
                except Exception:
                    pass
            if self._depth and depth is not None:
                cam.retrieve_measure(depth, sl.MEASURE.DEPTH_U16_MM)
                if self._depth_track is not None:
                    try:
                        self._depth_track.send(depth.get_data())
                    except Exception:
                        pass

    @property
    def calibration(self) -> Optional[dict]:
        return self._calib
