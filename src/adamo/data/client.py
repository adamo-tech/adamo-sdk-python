"""HTTP client for the Adamo store — download recorded session data."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterator

import httpx

from adamo._auth import (
    API_BASE,
    STORE_BASE,
    TokenInfo,
    exchange_api_key_for_token,
)
from adamo.data.models import Frame, Record, SessionMetadata, VideoIndex


def _to_rfc3339(t: str | float | datetime | None) -> str | None:
    """Normalize a user-supplied timestamp to RFC3339 for the store API."""
    if t is None:
        return None
    if isinstance(t, (int, float)):
        return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()
    if isinstance(t, datetime):
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t.isoformat()
    return t  # assume already a string


class DataClient:
    """Client for querying and downloading recorded session data from the Adamo store.

    Exchanges an API key for a short-lived JWT on first use and auto-refreshes
    when the token expires.

    Usage::

        from adamo.data import connect
        client = connect(api_key="ak_...")
        for session in client.list_sessions():
            print(session.name, session.message_count)
    """

    def __init__(
        self,
        api_key: str,
        *,
        api_url: str = API_BASE,
        store_url: str = STORE_BASE,
    ) -> None:
        self._api_key = api_key
        self._api_url = api_url
        self._store_url = store_url.rstrip("/")
        self._token: TokenInfo | None = None
        self._client = httpx.Client(timeout=30)

    def _ensure_token(self) -> TokenInfo:
        if self._token is None or self._token.expired:
            self._token = exchange_api_key_for_token(
                self._api_key, api_url=self._api_url
            )
        return self._token

    def _headers(self) -> dict[str, str]:
        token = self._ensure_token()
        return {
            "Authorization": f"Bearer {token.token}",
            "x-org-id": token.org_id,
        }

    def _get(self, path: str, *, params: dict | None = None) -> httpx.Response:
        resp = self._client.get(
            f"{self._store_url}{path}",
            headers=self._headers(),
            params=params,
        )
        resp.raise_for_status()
        return resp

    def _post(self, path: str, *, body: dict) -> httpx.Response:
        resp = self._client.post(
            f"{self._store_url}{path}",
            headers=self._headers(),
            json=body,
        )
        resp.raise_for_status()
        return resp

    def _stream(self, path: str, *, params: dict | None = None) -> httpx.Response:
        """Start a streaming GET request. Caller must close the response."""
        req = self._client.build_request(
            "GET",
            f"{self._store_url}{path}",
            headers=self._headers(),
            params=params,
        )
        resp = self._client.send(req, stream=True)
        resp.raise_for_status()
        return resp

    # -- Sessions --------------------------------------------------------------

    def list_sessions(
        self,
        *,
        after: str | float | datetime | None = None,
        before: str | float | datetime | None = None,
        name_contains: str | None = None,
    ) -> list[SessionMetadata]:
        """List recorded sessions, optionally filtered.

        Args:
            after: Only sessions started at or after this time.
            before: Only sessions started at or before this time.
            name_contains: Case-insensitive substring match on session name.
        """
        token = self._ensure_token()
        resp = self._get("/sessions", params={"org_id": token.org_id})
        sessions = [SessionMetadata.from_dict(s) for s in resp.json()]

        if after is not None:
            after_f = _ts_to_float(after)
            sessions = [s for s in sessions if s.started_at is not None and s.started_at >= after_f]
        if before is not None:
            before_f = _ts_to_float(before)
            sessions = [s for s in sessions if s.started_at is not None and s.started_at <= before_f]
        if name_contains is not None:
            needle = name_contains.lower()
            sessions = [s for s in sessions if needle in s.name.lower()]

        return sessions

    def get_session(self, session_id: str) -> SessionMetadata:
        """Get metadata for a single session."""
        resp = self._get(f"/sessions/{session_id}")
        return SessionMetadata.from_dict(resp.json())

    def get_topics(self, session_id: str) -> list[str]:
        """Get the list of topics recorded in a session."""
        resp = self._get(f"/sessions/{session_id}/topics")
        return resp.json()

    def match_topics(self, session_id: str, pattern: str) -> list[str]:
        """Get topics matching a glob pattern (e.g. ``robot/video/**``).

        Supports ``*`` (single segment) and ``**`` (any depth).
        """
        all_topics = self.get_topics(session_id)
        return _match_topic_pattern(all_topics, pattern)

    def message_count(self, session_id: str) -> int:
        """Get the total message count for a session."""
        resp = self._get(f"/sessions/{session_id}/count")
        return resp.json()["count"]

    # -- Records ---------------------------------------------------------------

    def query_records(
        self,
        session_id: str,
        *topics: str,
        start: str | float | datetime | None = None,
        end: str | float | datetime | None = None,
    ) -> list[Record]:
        """Query records in a session. Returns all matching records in memory.

        Topics support Zenoh-style wildcards: ``*`` matches one segment,
        ``**`` matches any number of segments.

        For large result sets, prefer :meth:`iter_records`.
        """
        return list(
            self.iter_records(session_id, *topics, start=start, end=end)
        )

    def iter_records(
        self,
        session_id: str,
        *topics: str,
        start: str | float | datetime | None = None,
        end: str | float | datetime | None = None,
    ) -> Iterator[Record]:
        """Stream records from a session — does not buffer the full response.

        Topics support Zenoh-style wildcards: ``*`` matches one segment,
        ``**`` matches any number of segments.

        Example::

            for r in client.iter_records(sid, "robot/sensors/**"):
                print(r.topic, r.timestamp, len(r.payload))
        """
        resolved = self._resolve_topics(session_id, list(topics)) if topics else None

        params: dict[str, str] = {}
        s = _to_rfc3339(start)
        e = _to_rfc3339(end)
        if s:
            params["start"] = s
        if e:
            params["end"] = e
        if resolved:
            params["topics"] = ",".join(resolved)

        resp = self._stream(f"/sessions/{session_id}/records", params=params)
        try:
            for line in resp.iter_lines():
                line = line.strip()
                if line:
                    yield Record.from_dict(json.loads(line))
        finally:
            resp.close()

    def export_records(
        self,
        session_id: str,
        *topics: str,
        start: str | float | datetime | None = None,
        end: str | float | datetime | None = None,
        chunk_size: int = 1000,
    ) -> Iterator[list[Record]]:
        """Export records in chunks. Yields lists of Records."""
        resolved = self._resolve_topics(session_id, list(topics)) if topics else None

        params: dict[str, str] = {"chunk_size": str(chunk_size)}
        s = _to_rfc3339(start)
        e = _to_rfc3339(end)
        if s:
            params["start"] = s
        if e:
            params["end"] = e
        if resolved:
            params["topics"] = ",".join(resolved)

        resp = self._stream(f"/sessions/{session_id}/export", params=params)
        try:
            for line in resp.iter_lines():
                line = line.strip()
                if line:
                    chunk = json.loads(line)
                    yield [Record.from_dict(r) for r in chunk.get("records", [])]
        finally:
            resp.close()

    # -- Aligned queries -------------------------------------------------------

    def aligned(
        self,
        session_id: str,
        *topics: str,
        start: str | float | datetime | None = None,
        end: str | float | datetime | None = None,
        window_ms: int = 50,
        hz: float | None = None,
    ) -> list[dict[str, Record]]:
        """Temporally align records across topics.

        Returns a list of dicts, one per aligned timestep. Each dict maps
        topic name to the matched :class:`Record` at that timestep.

        Topics support Zenoh-style wildcards.

        Args:
            session_id: The session to query.
            *topics: Two or more topic patterns to align.
            start: Start of time range.
            end: End of time range.
            window_ms: Maximum allowed time gap for a match (default 50ms).
            hz: If set, resample to this frequency instead of aligning to
                the first topic's timestamps.

        Example::

            pairs = client.aligned(
                sid,
                "robot/video/*",
                "robot/control/**/joint_states",
                window_ms=33,
            )
            for step in pairs:
                image_record = step["robot/video/main"]
                joints_record = step["robot/control/json/joint_states"]
        """
        if len(topics) < 2:
            raise ValueError("aligned() requires at least 2 topic patterns")

        # Resolve wildcards to concrete topics
        all_resolved = []
        for pattern in topics:
            matched = self._resolve_topics(session_id, [pattern])
            if not matched:
                raise ValueError(f"No topics matched pattern: {pattern!r}")
            all_resolved.append(matched)

        # Use the first pattern's topics as the "left" (anchor)
        left_topics = all_resolved[0]
        right_topics = []
        for group in all_resolved[1:]:
            right_topics.extend(group)

        s = _to_rfc3339(start)
        e = _to_rfc3339(end)

        # If no explicit range, use session bounds
        if not s or not e:
            meta = self.get_session(session_id)
            if not s and meta.started_at is not None:
                s = _to_rfc3339(meta.started_at)
            if not e and meta.stopped_at is not None:
                e = _to_rfc3339(meta.stopped_at)

        if not s or not e:
            raise ValueError(
                "Could not determine time range — provide start/end or use a session with known bounds"
            )

        body: dict = {
            "left_topics": left_topics,
            "right_topics": right_topics,
            "start": s,
            "end": e,
            "window_ms": window_ms,
            "join_type": "inner",
        }

        resp = self._post(f"/sessions/{session_id}/join", body=body)
        raw_records = resp.json()

        # Group the flat joined records into aligned timesteps.
        # The server returns records ordered by timestamp with "joined/" prefix.
        # Each left timestamp can have multiple matched right records.
        steps: dict[float, dict[str, Record]] = {}
        for raw in raw_records:
            r = Record.from_dict(raw)
            # Strip "joined/" prefix from topic
            topic = r.topic.removeprefix("joined/")
            r = Record(
                session_id=r.session_id,
                topic=topic,
                payload=r.payload,
                timestamp=r.timestamp,
            )
            step = steps.setdefault(r.timestamp, {})
            step[topic] = r

        result = [steps[ts] for ts in sorted(steps)]

        # Optional: resample to fixed hz
        if hz is not None and result:
            result = _resample(result, hz)

        return result

    # -- Video -----------------------------------------------------------------

    def video_index(self, session_id: str, topic: str) -> VideoIndex:
        """Get video index metadata for a recorded video topic."""
        resp = self._get(
            f"/sessions/{session_id}/video/index",
            params={"topic": topic},
        )
        return VideoIndex.from_dict(resp.json())

    def download_video(
        self,
        session_id: str,
        topic: str,
        output_path: str | Path,
    ) -> Path:
        """Download the full MP4 video for a topic and write it to disk."""
        output_path = Path(output_path)
        resp = self._stream(
            f"/sessions/{session_id}/video/mp4",
            params={"topic": topic},
        )
        try:
            with open(output_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    f.write(chunk)
        finally:
            resp.close()
        return output_path

    def iter_frames(
        self,
        session_id: str,
        topic: str,
        *,
        start: str | float | datetime | None = None,
        end: str | float | datetime | None = None,
        size: tuple[int, int] | None = None,
    ) -> Iterator[Frame]:
        """Iterate decoded video frames as numpy arrays.

        Downloads the MP4 and decodes frames using PyAV. Each yielded
        :class:`Frame` has an ``.image`` attribute of shape ``(H, W, 3)``
        uint8 RGB, and a ``.timestamp`` in epoch seconds.

        Requires ``av`` (``pip install av``).

        Args:
            session_id: The session to read from.
            topic: Exact video topic (no wildcards).
            start: Only yield frames at or after this time.
            end: Only yield frames at or before this time.
            size: If set, resize frames to ``(width, height)``.
        """
        try:
            import av
        except ImportError:
            raise ImportError(
                "PyAV is required for iter_frames(). "
                "Install it with: pip install av"
            ) from None

        try:
            import numpy as np
        except ImportError:
            raise ImportError(
                "numpy is required for iter_frames(). "
                "Install it with: pip install numpy"
            ) from None

        # Get the video index to map frame PTS → wall-clock timestamps
        idx = self.video_index(session_id, topic)
        if not idx.segments:
            return

        # Build a PTS → epoch seconds mapping from segment metadata
        seg_times: list[tuple[float, float]] = []  # (start_epoch, end_epoch)
        for seg in idx.segments:
            seg_start = models_parse_ts(seg.get("start_time", ""))
            seg_end = models_parse_ts(seg.get("end_time", ""))
            seg_times.append((seg_start, seg_end))

        session_start = seg_times[0][0] if seg_times else 0.0

        start_f = _ts_to_float(start) if start is not None else None
        end_f = _ts_to_float(end) if end is not None else None

        # Stream the MP4 bytes into a pipe for PyAV
        resp = self._stream(
            f"/sessions/{session_id}/video/mp4",
            params={"topic": topic},
        )
        try:
            # Write to a temp file since PyAV needs seekable input for MP4
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                tmp_path = tmp.name
                for chunk in resp.iter_bytes(chunk_size=65536):
                    tmp.write(chunk)
        finally:
            resp.close()

        try:
            container = av.open(tmp_path)
            stream = container.streams.video[0]
            time_base = float(stream.time_base)

            for frame in container.decode(video=0):
                # Convert PTS to wall-clock epoch seconds
                pts_sec = frame.pts * time_base if frame.pts is not None else 0.0
                epoch = session_start + pts_sec

                if start_f is not None and epoch < start_f:
                    continue
                if end_f is not None and epoch > end_f:
                    break

                rgb = frame.to_ndarray(format="rgb24")
                if size is not None:
                    w, h = size
                    rgb = np.array(
                        frame.to_image().resize((w, h)),
                        dtype=np.uint8,
                    )

                yield Frame(topic=topic, timestamp=epoch, image=rgb)

            container.close()
        finally:
            import os
            os.unlink(tmp_path)

    # -- Dataset (PyTorch) -----------------------------------------------------

    def dataset(
        self,
        sessions: list,
        observation: dict[str, str | tuple[str, str]],
        action: str | tuple[str, str],
        obs_steps: int = 1,
        action_steps: int = 1,
        hz: float = 30.0,
        image_size: tuple[int, int] | None = None,
    ):
        """Build a PyTorch-compatible Dataset for robot learning.

        Downloads and pre-processes all data up-front so that iteration
        is O(1) per sample.  Requires ``numpy``; ``torch`` is only needed
        when indexing samples.

        Install optional dependencies with ``pip install adamo[ml]``.

        Args:
            sessions: List of :class:`SessionMetadata` or session-ID strings.
            observation: Mapping from user key to topic spec.  Values are
                either a topic string (auto-detected as video or raw bytes)
                or a ``(topic_pattern, field_name)`` tuple for JSON payloads.
            action: A single topic spec — string or ``(pattern, field)`` tuple.
            obs_steps: Observation history length (default 1).
            action_steps: Action prediction horizon (default 1).
            hz: Resampling frequency in Hz (default 30).
            image_size: ``(width, height)`` to resize video frames, or None.

        Returns:
            An :class:`~adamo.data.dataset.AdamoDataset` instance.
        """
        from adamo.data.dataset import AdamoDataset

        return AdamoDataset(
            self,
            sessions=sessions,
            observation=observation,
            action=action,
            obs_steps=obs_steps,
            action_steps=action_steps,
            hz=hz,
            image_size=image_size,
        )

    # -- Episodes (trajectory-level access) ------------------------------------

    def episodes(
        self,
        *topics: str,
        sessions: list[str] | None = None,
        window_ms: int = 50,
    ) -> Iterator[dict[str, list[Record]]]:
        """Iterate over sessions as episodes — one dict per session.

        Each dict maps topic name to a time-ordered list of Records,
        temporally aligned across topics.

        This is the primary interface for trajectory-level training
        (diffusion policy, ACT, etc.).

        Args:
            *topics: Topic patterns (wildcards supported). First pattern is
                the anchor for temporal alignment.
            sessions: Session IDs to iterate. If None, uses all sessions.
            window_ms: Alignment window in milliseconds.

        Example::

            for ep in client.episodes("robot/video/*", "robot/control/**"):
                images = ep["robot/video/main"]     # list[Record], time-ordered
                joints = ep["robot/control/json/joint_states"]
                print(f"Episode: {len(images)} steps")
        """
        if len(topics) < 1:
            raise ValueError("episodes() requires at least 1 topic pattern")

        session_ids = sessions
        if session_ids is None:
            session_ids = [s.id for s in self.list_sessions()]

        for sid in session_ids:
            if len(topics) == 1:
                # Single topic — just stream records
                records = list(self.iter_records(sid, *topics))
                if records:
                    by_topic: dict[str, list[Record]] = {}
                    for r in records:
                        by_topic.setdefault(r.topic, []).append(r)
                    yield by_topic
            else:
                # Multiple topics — use server-side alignment
                steps = self.aligned(sid, *topics, window_ms=window_ms)
                if steps:
                    episode: dict[str, list[Record]] = {}
                    for step in steps:
                        for topic_name, record in step.items():
                            episode.setdefault(topic_name, []).append(record)
                    yield episode

    # -- DataFrame -------------------------------------------------------------

    def to_dataframe(
        self,
        session_id: str,
        *topics: str,
        start: str | float | datetime | None = None,
        end: str | float | datetime | None = None,
    ):
        """Load records into a pandas DataFrame.

        Requires ``pandas`` (install with ``pip install adamo[data]``).
        """
        try:
            import pandas as pd
        except ImportError:
            raise ImportError(
                "pandas is required for to_dataframe(). "
                "Install it with: pip install adamo[data]"
            ) from None

        records = self.query_records(session_id, *topics, start=start, end=end)
        return pd.DataFrame(
            [
                {
                    "session_id": r.session_id,
                    "topic": r.topic,
                    "timestamp": r.timestamp,
                    "payload": r.payload,
                }
                for r in records
            ]
        )

    # -- Lifecycle -------------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # -- Internal --------------------------------------------------------------

    def _resolve_topics(
        self, session_id: str, patterns: list[str]
    ) -> list[str]:
        """Expand wildcard topic patterns to concrete topic names."""
        has_wildcard = any("*" in p for p in patterns)
        if not has_wildcard:
            return patterns

        all_topics = self.get_topics(session_id)
        resolved = set()
        for pattern in patterns:
            if "*" in pattern:
                for t in _match_topic_pattern(all_topics, pattern):
                    resolved.add(t)
            else:
                resolved.add(pattern)
        return sorted(resolved)


# -- Topic matching (Zenoh-style wildcards) ------------------------------------


def _match_topic_pattern(all_topics: list[str], pattern: str) -> list[str]:
    """Match topics against a Zenoh-style glob pattern.

    ``*`` matches exactly one path segment, ``**`` matches any number.
    """
    # Convert Zenoh pattern to fnmatch-style glob
    # "**" → matches any path, "*" → matches one segment
    # We split on "/" and match segment by segment.
    pat_parts = pattern.split("/")
    return [t for t in all_topics if _segments_match(t.split("/"), pat_parts)]


def _segments_match(topic_parts: list[str], pat_parts: list[str]) -> bool:
    """Recursively match topic path segments against pattern segments."""
    ti, pi = 0, 0
    while pi < len(pat_parts) and ti < len(topic_parts):
        if pat_parts[pi] == "**":
            # ** matches zero or more segments
            if pi == len(pat_parts) - 1:
                return True  # trailing ** matches everything
            # Try matching remaining pattern at every position
            for skip in range(ti, len(topic_parts)):
                if _segments_match(topic_parts[skip:], pat_parts[pi + 1 :]):
                    return True
            return False
        elif pat_parts[pi] == "*" or fnmatch(topic_parts[ti], pat_parts[pi]):
            ti += 1
            pi += 1
        else:
            return False
    # Consume trailing **
    while pi < len(pat_parts) and pat_parts[pi] == "**":
        pi += 1
    return ti == len(topic_parts) and pi == len(pat_parts)


def _resample(
    steps: list[dict[str, Record]], hz: float
) -> list[dict[str, Record]]:
    """Resample aligned steps to a fixed frequency using nearest-neighbor."""
    if not steps or hz <= 0:
        return steps

    # Get time range from first topic's records
    all_ts = [
        r.timestamp for step in steps for r in step.values()
    ]
    t_start = min(all_ts)
    t_end = max(all_ts)
    interval = 1.0 / hz

    resampled = []
    t = t_start
    idx = 0
    while t <= t_end:
        # Find nearest step
        while idx < len(steps) - 1:
            ts_cur = next(iter(steps[idx].values())).timestamp
            ts_next = next(iter(steps[idx + 1].values())).timestamp
            if abs(ts_next - t) < abs(ts_cur - t):
                idx += 1
            else:
                break
        resampled.append(steps[idx])
        t += interval

    return resampled


def _ts_to_float(t: str | float | datetime | None) -> float | None:
    if t is None:
        return None
    if isinstance(t, (int, float)):
        return float(t)
    if isinstance(t, datetime):
        return t.timestamp()
    return models_parse_ts(t)


def models_parse_ts(s: str) -> float:
    """Re-export the timestamp parser from models."""
    from adamo.data.models import _parse_ts
    return _parse_ts(s)
