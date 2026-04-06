from adamo.operate import Session, connect, connect_async
from adamo import operate
from adamo.video import Robot, VideoTrack

__all__ = ["Session", "connect", "connect_async", "operate", "data", "Robot", "VideoTrack"]


def __getattr__(name: str):
    if name == "data":
        import importlib

        return importlib.import_module("adamo.data")
    raise AttributeError(f"module 'adamo' has no attribute {name!r}")
