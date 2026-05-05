"""Adamo Python SDK — stream video and data via Zenoh."""
from __future__ import annotations

from adamo.operate import Session, connect, connect_async
from adamo.operate.session import Publisher, Sample, Subscriber
from adamo.session import Robot, Participant

__all__ = [
    "connect",
    "connect_async",
    "Session",
    "Sample",
    "Publisher",
    "Subscriber",
    "Robot",
    "Participant",
    "VideoTrack",
    "data",
    "operate",
    "stats",
]


def __getattr__(name: str):
    # Lazy submodule imports — keeps `import adamo` cheap when the user
    # doesn't need the data / video helpers.
    if name == "data":
        import importlib
        return importlib.import_module("adamo.data")
    if name == "VideoTrack":
        from adamo._video import VideoTrack as _VT
        return _VT
    if name == "operate":
        import importlib
        return importlib.import_module("adamo.operate")
    if name == "stats":
        import importlib
        return importlib.import_module("adamo.stats")
    raise AttributeError(f"module 'adamo' has no attribute {name!r}")
