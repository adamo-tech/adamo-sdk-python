"""Control message types for Adamo — JSON encoding/decoding."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Union


@dataclass
class JointState:
    """Mirrors sensor_msgs/JointState."""

    names: list[str] = field(default_factory=list)
    positions: list[float] = field(default_factory=list)
    velocity: list[float] = field(default_factory=list)
    effort: list[float] = field(default_factory=list)
    stamp: float = 0.0
    frame_id: str = ""

    def to_json(self) -> bytes:
        if self.stamp == 0.0:
            self.stamp = time.time()
        return json.dumps(
            {
                "type": "JointState",
                "stamp": self.stamp,
                "frame_id": self.frame_id,
                "names": self.names,
                "positions": self.positions,
                "velocity": self.velocity,
                "effort": self.effort,
            },
            separators=(",", ":"),
        ).encode()


@dataclass
class Joy:
    """Mirrors sensor_msgs/Joy."""

    axes: list[float] = field(default_factory=list)
    buttons: list[int] = field(default_factory=list)
    stamp: float = 0.0

    def to_json(self) -> bytes:
        if self.stamp == 0.0:
            self.stamp = time.time()
        return json.dumps(
            {
                "type": "Joy",
                "stamp": self.stamp,
                "axes": self.axes,
                "buttons": self.buttons,
            },
            separators=(",", ":"),
        ).encode()


def decode_control(payload: bytes) -> Union[JointState, Joy, dict]:
    """Decode a control message from bytes.

    Returns a typed object for known message types, or a raw dict for unknown JSON.
    """
    obj = json.loads(payload)
    msg_type = obj.get("type")

    if msg_type == "JointState":
        return JointState(
            names=obj.get("names", []),
            positions=obj.get("positions", []),
            velocity=obj.get("velocity", []),
            effort=obj.get("effort", []),
            stamp=obj.get("stamp", 0.0),
            frame_id=obj.get("frame_id", ""),
        )

    if msg_type == "Joy":
        return Joy(
            axes=obj.get("axes", []),
            buttons=obj.get("buttons", []),
            stamp=obj.get("stamp", 0.0),
        )

    return obj
