"""Control message types for Adamo — CDR and JSON encoding/decoding."""

from __future__ import annotations

import json
import struct
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


@dataclass
class JoystickCommand:
    """Adamo joystick command with sequence ID for packet ordering."""

    sequence_id: int = 0
    stamp_sec: int = 0
    stamp_nanosec: int = 0
    axes: list[float] = field(default_factory=list)
    buttons: list[int] = field(default_factory=list)

    @property
    def stamp(self) -> float:
        """Timestamp as a float (seconds since epoch)."""
        return self.stamp_sec + self.stamp_nanosec / 1e9


def _decode_ros_envelope(payload: bytes) -> tuple[str, str, memoryview]:
    """Decode a ROS envelope: topic + type + CDR payload.

    Returns (topic, msg_type, cdr_bytes).
    """
    mv = memoryview(payload)
    off = 0
    topic_len = struct.unpack_from(">I", mv, off)[0]
    off += 4
    topic = bytes(mv[off : off + topic_len]).decode()
    off += topic_len
    type_len = struct.unpack_from(">I", mv, off)[0]
    off += 4
    msg_type = bytes(mv[off : off + type_len]).decode()
    off += type_len
    return topic, msg_type, mv[off:]


def _decode_joystick_command_cdr(cdr: memoryview | bytes) -> JoystickCommand:
    """Decode CDR-encoded JoystickCommand (skips 4-byte CDR header)."""
    off = 4  # skip CDR encapsulation header
    seq_id = struct.unpack_from("<I", cdr, off)[0]
    off += 4
    sec = struct.unpack_from("<i", cdr, off)[0]
    off += 4
    nanosec = struct.unpack_from("<I", cdr, off)[0]
    off += 4
    axes_len = struct.unpack_from("<I", cdr, off)[0]
    off += 4
    axes = list(struct.unpack_from(f"<{axes_len}f", cdr, off))
    off += axes_len * 4
    buttons_len = struct.unpack_from("<I", cdr, off)[0]
    off += 4
    buttons = list(struct.unpack_from(f"<{buttons_len}i", cdr, off))
    return JoystickCommand(
        sequence_id=seq_id,
        stamp_sec=sec,
        stamp_nanosec=nanosec,
        axes=axes,
        buttons=buttons,
    )


def decode_control(payload: bytes) -> Union[JointState, Joy, JoystickCommand, dict]:
    """Decode a control message from bytes.

    Handles both CDR (ROS envelope) and legacy JSON formats.
    Returns a typed object for known message types, or a raw dict for unknown JSON.
    """
    # ROS envelope: starts with a big-endian uint32 topic length.
    # JSON always starts with '{' (0x7b). If the first byte looks like
    # a plausible length prefix (not printable ASCII), try envelope decoding.
    if len(payload) >= 8 and payload[0] == 0:
        try:
            _topic, msg_type, cdr = _decode_ros_envelope(payload)
            if msg_type == "adamo_msgs/msg/JoystickCommand":
                return _decode_joystick_command_cdr(cdr)
        except (struct.error, UnicodeDecodeError):
            pass  # fall through to JSON

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
