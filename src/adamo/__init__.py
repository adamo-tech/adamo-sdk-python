from __future__ import annotations

from adamo.session import Robot, Participant, VideoTrack
from adamo._native import DataTrack

__all__ = ["Robot", "Participant", "VideoTrack", "DataTrack", "data"]


def __getattr__(name: str):
    if name == "data":
        import importlib

        return importlib.import_module("adamo.data")
    raise AttributeError(f"module 'adamo' has no attribute {name!r}")
