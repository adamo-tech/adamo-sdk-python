from adamo.session import Robot, VideoTrack

__all__ = ["Robot", "VideoTrack", "data"]


def __getattr__(name: str):
    if name == "data":
        import importlib

        return importlib.import_module("adamo.data")
    raise AttributeError(f"module 'adamo' has no attribute {name!r}")
