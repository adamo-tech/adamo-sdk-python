"""Generic V4L2 camera adapter.

Handles UVC webcams, plus the *color* stream of ZED and RealSense cameras —
both of which expose themselves as V4L2 devices in addition to their vendor
SDK. For depth/IMU/calibration, use the dedicated vendor adapter.

Discovery is intentionally cheap: it lists `/dev/video*` and reads the
human-readable name from `/sys/class/video4linux/<name>/name`. Full mode
enumeration is delegated to the Rust binary's auto-mode (which already
runs the picker on every discovered device).
"""
from __future__ import annotations

import glob
import os
import sys
from typing import Optional

from .base import AttachOptions, CameraInfo


_ZED_NAMES = ("ZED", "STEREOLABS")
_REALSENSE_NAMES = ("REALSENSE", "RealSense")


def _read_sysfs_name(devpath: str) -> str:
    base = os.path.basename(devpath)
    sysfile = f"/sys/class/video4linux/{base}/name"
    try:
        with open(sysfile, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _is_capture_node(devpath: str) -> bool:
    """Cheap filter: read /sys capabilities; require the CAPTURE bit."""
    base = os.path.basename(devpath)
    sysfile = f"/sys/class/video4linux/{base}/capabilities"
    try:
        with open(sysfile, "r", encoding="utf-8") as fh:
            caps = int(fh.read().strip(), 16)
    except (OSError, ValueError):
        return True  # fall through to ioctl path on open
    V4L2_CAP_VIDEO_CAPTURE = 0x00000001
    return bool(caps & V4L2_CAP_VIDEO_CAPTURE)


def discover() -> list[CameraInfo]:
    """List V4L2 capture nodes on the system.

    On non-Linux platforms returns an empty list.
    """
    if not sys.platform.startswith("linux"):
        return []
    out: list[CameraInfo] = []
    paths = sorted(glob.glob("/dev/video*"))
    for path in paths:
        # Filter to /dev/videoN (skip /dev/video-* alias nodes).
        suffix = path.replace("/dev/video", "")
        if not suffix.isdigit():
            continue
        if not _is_capture_node(path):
            continue
        name = _read_sysfs_name(path)
        # Tag ZED / RealSense color nodes so callers can route them to the
        # vendor adapter when they want depth/IMU.
        upper = name.upper()
        is_zed = any(tok in upper for tok in _ZED_NAMES)
        is_realsense = any(tok in upper for tok in _REALSENSE_NAMES)
        out.append(
            CameraInfo(
                vendor="v4l2",
                model=name or "v4l2",
                serial=path,
                handle=path,
                extra={
                    "looks_like_zed": is_zed,
                    "looks_like_realsense": is_realsense,
                    "sysfs_name": name,
                },
            )
        )
    return out


def attach(
    robot,
    info: CameraInfo,
    *,
    name: Optional[str] = None,
    options: Optional[AttachOptions] = None,
) -> None:
    """Attach a V4L2 device to the robot as an adamo video track.

    The device path lives in ``info.handle``. Mode selection happens
    Rust-side (the picker runs on the actual device); we simply pass the
    device through to ``robot.attach(device=...)``.
    """
    if options is None:
        options = AttachOptions()
    track_name = name or _name_from_path(info.handle)
    width, height = options.max_resolution
    robot.attach(
        track_name,
        device=info.handle,
        width=width,
        height=height,
        fps=options.prefer_fps,
        codec=options.codec,
        encoder=options.encoder,
        bitrate_kbps=options.bitrate_kbps,
    )


def _name_from_path(devpath: str) -> str:
    base = os.path.basename(devpath)
    sysname = _read_sysfs_name(devpath)
    if sysname:
        # Lowercase, replace whitespace with underscore, drop noise.
        clean = "".join(
            c if c.isalnum() else "_" for c in sysname.lower()
        ).strip("_")
        return f"{clean}_{base}"
    return base
