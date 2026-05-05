"""Common types for the adamo.cameras vendor adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CameraInfo:
    """Identifying metadata for a discovered camera.

    Vendor adapters return one of these per detected device. The `vendor`
    field selects which adapter handles it; everything else is informational
    or used for adamo track naming.
    """

    vendor: str  # "v4l2" | "zed" | "realsense" | "oak"
    model: str
    serial: str
    # Vendor-specific identifier the adapter uses to open the device.
    # V4L2: device path. ZED: serial number. RealSense: serial. OAK: mxid.
    handle: str
    # Optional capability hints — populated where cheap to detect.
    has_depth: bool = False
    has_imu: bool = False
    has_onboard_encode: bool = False  # OAK-only
    # Filled when the adapter publishes calibration into the track.
    intrinsics: Optional[list[float]] = None  # [fx, fy, cx, cy]
    extrinsics: Optional[list[float]] = None  # [x, y, z, qx, qy, qz, qw]
    extra: dict = field(default_factory=dict)


@dataclass
class AttachOptions:
    """Per-camera attach knobs. Mirrors the Rust auto-mode picker."""

    prefer_fps: int = 60  # falls back to 30 if the device can't do 60
    max_resolution: tuple[int, int] = (1920, 1080)
    bitrate_kbps: int = 4000
    codec: str = "h264"
    # Encoder override; leave None to let the Robot pick a default per platform.
    encoder: Optional[str] = None
    # If True, vendor adapters emit depth + IMU in addition to color where
    # supported. Otherwise color only.
    enable_depth: bool = False
    enable_imu: bool = False
