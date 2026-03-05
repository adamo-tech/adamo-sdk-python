"""Data models for recorded session data from the Adamo store."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _parse_ts(s: str | None) -> float:
    """Parse an RFC3339 timestamp string to epoch seconds (float).

    Returns 0.0 for None or empty strings.
    """
    if not s:
        return 0.0
    # Handle Z suffix and +00:00
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s).timestamp()


def _parse_ts_or_none(s: str | None) -> float | None:
    if not s:
        return None
    return _parse_ts(s)


@dataclass
class SessionMetadata:
    """Metadata for a recorded session."""

    id: str
    name: str
    status: str
    topics: list[str]
    started_at: float | None  # epoch seconds
    stopped_at: float | None  # epoch seconds
    message_count: int
    org_id: str

    @classmethod
    def from_dict(cls, d: dict) -> SessionMetadata:
        return cls(
            id=d["id"],
            name=d.get("name", ""),
            status=d.get("status", ""),
            topics=d.get("topics", []),
            started_at=_parse_ts_or_none(d.get("started_at")),
            stopped_at=_parse_ts_or_none(d.get("stopped_at")),
            message_count=d.get("message_count", 0),
            org_id=d.get("org_id", ""),
        )


@dataclass
class Record:
    """A single recorded message."""

    session_id: str
    topic: str
    payload: bytes
    timestamp: float  # epoch seconds

    @classmethod
    def from_dict(cls, d: dict) -> Record:
        raw = d.get("payload", "")
        payload = base64.b64decode(raw) if isinstance(raw, str) else raw
        return cls(
            session_id=d.get("session_id", ""),
            topic=d.get("topic", ""),
            payload=payload,
            timestamp=_parse_ts(d.get("timestamp", "")),
        )


@dataclass
class VideoIndex:
    """Video index metadata for a recorded video topic."""

    session_id: str
    topic: str
    frame_count: int
    keyframe_count: int
    duration_ms: int
    avg_fps: float
    segments: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> VideoIndex:
        return cls(
            session_id=d.get("session_id", ""),
            topic=d.get("topic", ""),
            frame_count=d.get("frame_count", 0),
            keyframe_count=d.get("keyframe_count", 0),
            duration_ms=d.get("duration_ms", 0),
            avg_fps=d.get("avg_fps", 0.0),
            segments=d.get("segments", []),
        )


@dataclass
class Frame:
    """A decoded video frame."""

    topic: str
    timestamp: float  # epoch seconds
    image: object  # numpy ndarray (H, W, 3) uint8 RGB — typed as object to avoid hard numpy dep

    @property
    def height(self) -> int:
        return self.image.shape[0]

    @property
    def width(self) -> int:
        return self.image.shape[1]
