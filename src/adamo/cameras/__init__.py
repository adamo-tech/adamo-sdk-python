"""Vendor camera adapters for adamo.

Three vendor adapters cover the cameras most adamo customers run:

- :mod:`adamo.cameras.v4l2` — generic UVC, plus the V4L2 color stream of
  ZED and RealSense (does not require any vendor SDK).
- :mod:`adamo.cameras.zed` — Stereolabs SDK (depth, IMU, calibration).
- :mod:`adamo.cameras.realsense` — Intel librealsense2 (depth, alignment,
  IMU, calibration).
- :mod:`adamo.cameras.oak` — Luxonis DepthAI (mandatory; OAKs aren't V4L2),
  with optional on-device H.264 passthrough.

Each adapter's vendor SDK is an *optional* import, so this package is safe
to load on hosts that only have one (or none) of them installed.

Top-level helpers:

- :func:`discover` — list every camera the host can see across all adapters.
- :func:`attach_all` — discover + attach each in one call.
"""
from __future__ import annotations

from typing import Optional

from .base import AttachOptions, CameraInfo


def discover() -> list[CameraInfo]:
    """Discover cameras across all installed vendor SDKs + V4L2.

    Adapters whose SDKs aren't installed return an empty list silently.
    """
    from . import v4l2, zed, realsense, oak

    out: list[CameraInfo] = []
    for module in (v4l2, oak, zed, realsense):
        try:
            out.extend(module.discover())
        except Exception:
            # An adapter that throws shouldn't take the whole discovery down.
            continue
    return out


def attach_all(
    robot,
    *,
    options: Optional[AttachOptions] = None,
    skip_v4l2_for_known_vendors: bool = True,
) -> list[CameraInfo]:
    """Discover every camera and attach each as an adamo video track.

    When ``skip_v4l2_for_known_vendors`` is True (default), V4L2 nodes that
    look like ZED or RealSense color streams are skipped *if* the vendor
    SDK has already produced a discovery result for that camera — avoids
    publishing the same color stream twice.
    """
    from . import v4l2 as v4l2_mod, zed as zed_mod, realsense as rs_mod, oak as oak_mod

    opts = options or AttachOptions()
    discovered = discover()

    have_zed = any(c.vendor == "zed" for c in discovered)
    have_rs = any(c.vendor == "realsense" for c in discovered)

    attached: list[CameraInfo] = []
    for info in discovered:
        if info.vendor == "v4l2" and skip_v4l2_for_known_vendors:
            if have_zed and info.extra.get("looks_like_zed"):
                continue
            if have_rs and info.extra.get("looks_like_realsense"):
                continue

        try:
            if info.vendor == "v4l2":
                v4l2_mod.attach(robot, info, options=opts)
            elif info.vendor == "zed":
                cam = zed_mod.ZedCamera(
                    serial=int(info.serial) if info.serial.isdigit() else None,
                    fps=opts.prefer_fps,
                    depth=opts.enable_depth,
                )
                cam.attach(robot, name=f"zed_{info.serial}", options=opts)
            elif info.vendor == "realsense":
                cam = rs_mod.RealSenseCamera(
                    serial=info.serial,
                    width=opts.max_resolution[0],
                    height=opts.max_resolution[1],
                    fps=opts.prefer_fps,
                    depth=opts.enable_depth,
                )
                cam.attach(robot, name=f"realsense_{info.serial}", options=opts)
            elif info.vendor == "oak":
                cam = oak_mod.OakCamera(
                    mxid=info.serial,
                    width=opts.max_resolution[0],
                    height=opts.max_resolution[1],
                    fps=opts.prefer_fps,
                )
                cam.attach(robot, name=f"oak_{info.serial}", options=opts)
            attached.append(info)
        except Exception:
            # Best-effort: skip cameras that fail to attach (e.g. ZED SDK
            # missing CUDA on a non-NVIDIA host).
            continue
    return attached


__all__ = [
    "AttachOptions",
    "CameraInfo",
    "discover",
    "attach_all",
]
