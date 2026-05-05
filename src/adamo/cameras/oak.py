"""Luxonis OAK camera adapter (DepthAI v3).

OAKs are NOT V4L2 devices — they use XLink over USB or PoE and require the
DepthAI SDK. This adapter pulls raw NV12 frames via the host queue and
publishes them through iceoryx2 to the Rust pipeline for encoding.

Install: ``pip install depthai`` (v3+).
"""
from __future__ import annotations

import threading
from typing import Optional

from .base import AttachOptions, CameraInfo


def _import_dai():
    try:
        import depthai as dai  # type: ignore
    except ImportError as e:
        raise ImportError(
            "depthai is not installed. Install with `pip install depthai` (v3+)."
        ) from e
    if not hasattr(dai, "Pipeline"):
        raise RuntimeError("depthai >=3.0 required; older v2 API not supported.")
    return dai


def discover() -> list[CameraInfo]:
    try:
        dai = _import_dai()
    except ImportError:
        return []
    out: list[CameraInfo] = []
    try:
        devs = dai.Device.getAllAvailableDevices()
    except Exception:
        return []
    for d in devs:
        out.append(
            CameraInfo(
                vendor="oak",
                model=str(getattr(d, "name", "OAK")),
                serial=str(getattr(d, "mxid", "")),
                handle=str(getattr(d, "mxid", "")),
                has_depth=True,
                has_imu=True,  # most OAKs ship with BNO085; safe default
                has_onboard_encode=False,
                extra={"state": str(getattr(d, "state", ""))},
            )
        )
    return out


class OakCamera:
    """OAK camera publishing raw NV12 frames into an adamo track."""

    def __init__(
        self,
        *,
        mxid: Optional[str] = None,
        width: int = 1920,
        height: int = 1080,
        fps: int = 30,
    ):
        self._dai = _import_dai()
        self._mxid = mxid
        self._width = width
        self._height = height
        self._fps = fps
        self._device = None
        self._pipeline = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._track = None
        self._raw_queue_name = "rawout"

    def open(self) -> None:
        dai = self._dai
        pipeline = dai.Pipeline()
        cam = pipeline.create(dai.node.Camera).build(
            boardSocket=dai.CameraBoardSocket.CAM_A
        )
        # v3 unified Camera.requestOutput() API.
        out = cam.requestOutput(
            (self._width, self._height), dai.ImgFrame.Type.NV12, fps=self._fps
        )
        out.createOutputQueue(self._raw_queue_name)

        if self._mxid:
            info = dai.DeviceInfo(self._mxid)
            self._device = dai.Device(pipeline, info)
        else:
            self._device = dai.Device(pipeline)
        self._pipeline = pipeline

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._device is not None:
            self._device.close()
            self._device = None

    def attach(
        self,
        robot,
        *,
        name: str = "oak",
        options: Optional[AttachOptions] = None,
    ) -> None:
        if self._device is None:
            self.open()
        opts = options or AttachOptions(prefer_fps=self._fps)
        self._track = robot.video(
            name=name,
            width=self._width,
            height=self._height,
            pixel_format="NV12",
            codec=opts.codec,
            encoder=opts.encoder,
            bitrate_kbps=opts.bitrate_kbps,
            fps=self._fps,
        )

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name=f"adamo-oak-{name}", daemon=True
        )
        self._thread.start()

    def _run_loop(self) -> None:
        assert self._device is not None
        queue = self._device.getOutputQueue(
            self._raw_queue_name, maxSize=4, blocking=False
        )
        while not self._stop.is_set():
            pkt = queue.tryGet()
            if pkt is None:
                continue
            if self._track is not None:
                try:
                    self._track.send(pkt.getCvFrame())
                except Exception:
                    pass
