"""Python-fed video track — pushes numpy frames through iceoryx2 shared memory
to the Rust SHM source for hardware encoding + Zenoh transport."""
from __future__ import annotations

import ctypes
import threading
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


_PIXEL_BYTES = {
    "BGRA": 4,
    "RGBA": 4,
    "BGRX": 4,
    "RGBX": 4,
    "RGB": 3,
    "BGR": 3,
    "YUY2": 2,
    "UYVY": 2,
    "I420": None,  # 1.5 bytes/pixel — computed as width*height*3/2
    "NV12": None,  # 1.5 bytes/pixel
}


def _frame_size(width: int, height: int, pixel_format: str) -> int:
    fmt = pixel_format.upper()
    bpp = _PIXEL_BYTES.get(fmt)
    if bpp is None:
        # planar 4:2:0 formats: 1.5 bytes/pixel
        if fmt in ("I420", "NV12"):
            return (width * height * 3) // 2
        raise ValueError(f"Unsupported pixel_format: {pixel_format}")
    return width * height * bpp


class VideoTrack:
    """Python-side handle to a video track.

    Call :meth:`send` with a numpy array (or bytes) to feed a frame into the
    Rust pipeline. Frames travel via iceoryx2 shared memory (zero-copy in the
    same host) and are picked up by the encoder + Zenoh transport running in
    the Rust ``Robot.run()`` thread.

    Pixel layout must match the ``pixel_format``/``width``/``height`` passed
    to :meth:`adamo.Robot.video`. Arrays are expected to be C-contiguous.
    """

    def __init__(
        self,
        *,
        name: str,
        width: int,
        height: int,
        pixel_format: str,
        service_name: str,
    ):
        try:
            import iceoryx2 as iox2
        except ImportError as e:
            raise ImportError(
                "iceoryx2 is required for video(). "
                "Install with: pip install 'adamo[video]'"
            ) from e

        self.name = name
        self.width = int(width)
        self.height = int(height)
        self.pixel_format = pixel_format.upper()
        self._service_name = service_name
        self._expected_size = _frame_size(self.width, self.height, self.pixel_format)
        self._lock = threading.Lock()
        self._closed = False

        node = iox2.NodeBuilder.new().create(iox2.ServiceType.Ipc)
        svc = (
            node.service_builder(iox2.ServiceName.new(service_name))
            .publish_subscribe(iox2.Slice[ctypes.c_uint8])
            .enable_safe_overflow(True)
            .subscriber_max_buffer_size(2)
            .open_or_create()
        )
        self._node = node
        self._publisher = (
            svc.publisher_builder()
            .initial_max_slice_len(self._expected_size)
            .create()
        )
        # Hooked by Robot.video() so the first send() auto-starts the
        # Rust pipeline if the user isn't calling robot.run() themselves.
        self._on_first_send = None
        self._first_send_done = False

    @property
    def service_name(self) -> str:
        return self._service_name

    def send(self, frame) -> None:
        """Publish one frame.

        ``frame`` may be a numpy array or a ``bytes``-like object. Arrays
        should be C-contiguous — non-contiguous arrays are copied.
        """
        if self._closed:
            raise RuntimeError(f"VideoTrack '{self.name}' is closed")

        if hasattr(frame, "tobytes"):
            if hasattr(frame, "flags") and not frame.flags["C_CONTIGUOUS"]:
                import numpy as np
                frame = np.ascontiguousarray(frame)
            data = frame.tobytes()
        else:
            data = bytes(frame)

        if len(data) != self._expected_size:
            raise ValueError(
                f"VideoTrack '{self.name}': expected {self._expected_size} bytes "
                f"({self.width}x{self.height} {self.pixel_format}), got {len(data)}"
            )

        with self._lock:
            if not self._first_send_done:
                self._first_send_done = True
                hook = self._on_first_send
                if hook is not None:
                    hook()
            sample = self._publisher.loan_slice_uninit(len(data))
            ctypes.memmove(sample.payload_ptr, data, len(data))
            sample.assume_init().send()

    def close(self) -> None:
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def allocate_service_name(track_name: str) -> str:
    """Allocate a unique iceoryx2 service name for a Python-fed track.

    iceoryx2 services are global to the host, so we append a short uuid
    fragment to avoid collisions between concurrent processes.
    """
    suffix = uuid.uuid4().hex[:8]
    safe = track_name.replace("/", "_")
    return f"adamo/py/{safe}/{suffix}"
