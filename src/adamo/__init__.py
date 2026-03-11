from adamo.operate import Session, connect, connect_async
from adamo import operate

__all__ = ["Session", "connect", "connect_async", "operate", "data"]


def __getattr__(name: str):
    if name == "data":
        import importlib

        return importlib.import_module("adamo.data")
    raise AttributeError(f"module 'adamo' has no attribute {name!r}")
