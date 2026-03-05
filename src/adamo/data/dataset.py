"""PyTorch-compatible Dataset for robot learning from recorded Adamo sessions.

All I/O (downloading, decoding) happens during construction.
``__getitem__`` is pure O(1) numpy slicing + tensor conversion.
"""

from __future__ import annotations

import json
import sys
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from adamo.data.client import DataClient


# ---------------------------------------------------------------------------
# Topic spec types
# ---------------------------------------------------------------------------

@dataclass
class _TopicSpec:
    """Internal representation of a user-provided topic specification."""

    user_key: str  # e.g. "images.main" or "state"
    pattern: str  # e.g. "robot/video/main" or "robot/control/**/joint_states"
    field: str | None  # e.g. "positions" (None for raw / video topics)
    is_video: bool = False
    resolved: str = ""  # filled after wildcard resolution


# ---------------------------------------------------------------------------
# Nearest-neighbour alignment
# ---------------------------------------------------------------------------

def _align(source_ts: np.ndarray, target_ts: np.ndarray, source_data: np.ndarray) -> np.ndarray:
    """Align *source_data* to *target_ts* via nearest-neighbour lookup.

    Both ``source_ts`` and ``target_ts`` must be sorted 1-D float arrays.
    Returns ``source_data`` reindexed to match ``target_ts``.
    """
    idx = np.searchsorted(source_ts, target_ts, side="left")
    idx = np.clip(idx, 0, len(source_ts) - 1)
    left = np.clip(idx - 1, 0, len(source_ts) - 1)
    use_left = np.abs(source_ts[left] - target_ts) < np.abs(source_ts[idx] - target_ts)
    return source_data[np.where(use_left, left, idx)]


def _align_ts(source_ts: np.ndarray, target_ts: np.ndarray) -> np.ndarray:
    """Return index array that maps *target_ts* → nearest *source_ts* indices."""
    idx = np.searchsorted(source_ts, target_ts, side="left")
    idx = np.clip(idx, 0, len(source_ts) - 1)
    left = np.clip(idx - 1, 0, len(source_ts) - 1)
    use_left = np.abs(source_ts[left] - target_ts) < np.abs(source_ts[idx] - target_ts)
    return np.where(use_left, left, idx)


# ---------------------------------------------------------------------------
# Episode container
# ---------------------------------------------------------------------------

@dataclass
class _Episode:
    """Pre-processed episode data, aligned to a uniform timeline."""

    session_id: str
    length: int  # number of resampled timesteps
    aligned: dict[str, np.ndarray]  # resolved_topic → (T, ...) array


# ---------------------------------------------------------------------------
# AdamoDataset
# ---------------------------------------------------------------------------

class AdamoDataset:
    """A PyTorch-compatible ``Dataset`` for robot learning.

    Downloads and pre-processes recorded session data so that every call to
    ``__getitem__`` is O(1) — no network I/O, no decoding.

    Each sample is a ``dict[str, Tensor]`` with dot-separated keys:

    * ``"observation.<key>"`` for each entry in *observation*
    * ``"action"`` for the action spec

    Temporal windowing is handled automatically: observation tensors have
    shape ``(obs_steps, ...)``, action tensors ``(action_steps, ...)``.

    Args:
        client: A connected :class:`~adamo.data.client.DataClient`.
        sessions: List of :class:`~adamo.data.models.SessionMetadata` or
            session-ID strings.
        observation: Mapping from user key to topic spec. Each value is
            either a topic string (auto-detected as video or raw) or a
            ``(topic_pattern, field_name)`` tuple for JSON-encoded payloads.
        action: A single topic spec — string or ``(pattern, field)`` tuple.
        obs_steps: Number of observation timesteps per sample (default 1).
        action_steps: Number of action timesteps per sample (default 1).
        hz: Resampling frequency in Hz (default 30).
        image_size: ``(width, height)`` to resize video frames, or ``None``.
    """

    def __init__(
        self,
        client: DataClient,
        *,
        sessions: list[Any],
        observation: dict[str, str | tuple[str, str]],
        action: str | tuple[str, str],
        obs_steps: int = 1,
        action_steps: int = 1,
        hz: float = 30.0,
        image_size: tuple[int, int] | None = None,
    ) -> None:
        self._obs_steps = obs_steps
        self._action_steps = action_steps

        # --- Parse specs ---
        obs_specs = _parse_obs_specs(observation)
        action_spec = _parse_action_spec(action)

        # --- Normalize session list to IDs ---
        session_ids = _normalize_sessions(sessions)

        # --- Build episodes ---
        self._episodes: list[_Episode] = []
        self._obs_specs = obs_specs
        self._action_spec = action_spec

        for i, sid in enumerate(session_ids):
            _log(f"[{i + 1}/{len(session_ids)}] Processing session {sid}")
            ep = _build_episode(
                client, sid, obs_specs, action_spec,
                hz=hz, image_size=image_size,
            )
            if ep is not None:
                self._episodes.append(ep)

        if not self._episodes:
            warnings.warn("AdamoDataset: no valid episodes were loaded")

        # --- Build flat sample index ---
        self._index: list[tuple[int, int]] = []  # (episode_idx, local_t)
        for ep_idx, ep in enumerate(self._episodes):
            t_start = obs_steps - 1
            t_end = ep.length - action_steps
            for t in range(t_start, t_end + 1):
                self._index.append((ep_idx, t))

        # --- Compute stats (mean/std for non-video keys) ---
        self.stats: dict[str, dict[str, np.ndarray]] = {}
        self._compute_stats()

        _log(f"Dataset ready: {len(self._episodes)} episodes, {len(self._index)} samples")

    # -- torch Dataset interface -----------------------------------------------

    def __len__(self) -> int:
        return len(self._index)

    def __getitem__(self, idx: int) -> dict[str, Any]:
        try:
            from torch import from_numpy
        except ImportError:
            raise ImportError(
                "PyTorch is required for AdamoDataset.__getitem__(). "
                "Install it with: pip install torch"
            ) from None

        ep_idx, t = self._index[idx]
        episode = self._episodes[ep_idx]
        sample: dict[str, Any] = {}

        # Observation: slice [t - obs_steps + 1 : t + 1]
        obs_start = t - self._obs_steps + 1
        obs_end = t + 1
        for spec in self._obs_specs:
            data = episode.aligned[spec.resolved][obs_start:obs_end]
            if spec.is_video:
                # (To, H, W, 3) → (To, 3, H, W) float [0, 1]
                tensor = from_numpy(data.copy()).permute(0, 3, 1, 2).float() / 255.0
            else:
                tensor = from_numpy(data.copy()).float()
            sample[f"observation.{spec.user_key}"] = tensor

        # Action: slice [t : t + action_steps]
        act_data = episode.aligned[self._action_spec.resolved][t:t + self._action_steps]
        sample["action"] = from_numpy(act_data.copy()).float()

        return sample

    # -- Stats -----------------------------------------------------------------

    def _compute_stats(self) -> None:
        """Compute mean/std for non-video observation keys and the action key."""
        keys_to_stat: list[tuple[str, str]] = []  # (sample_key, resolved_topic)
        for spec in self._obs_specs:
            if not spec.is_video:
                keys_to_stat.append((f"observation.{spec.user_key}", spec.resolved))
        keys_to_stat.append(("action", self._action_spec.resolved))

        for sample_key, resolved in keys_to_stat:
            all_data = [ep.aligned[resolved] for ep in self._episodes if resolved in ep.aligned]
            if not all_data:
                continue
            cat = np.concatenate(all_data, axis=0)
            self.stats[sample_key] = {
                "mean": cat.mean(axis=0).astype(np.float32),
                "std": cat.std(axis=0).astype(np.float32),
            }


# ---------------------------------------------------------------------------
# Spec parsing
# ---------------------------------------------------------------------------

def _parse_obs_specs(observation: dict[str, str | tuple[str, str]]) -> list[_TopicSpec]:
    specs = []
    for key, val in observation.items():
        if isinstance(val, str):
            specs.append(_TopicSpec(user_key=key, pattern=val, field=None))
        elif isinstance(val, tuple) and len(val) == 2:
            specs.append(_TopicSpec(user_key=key, pattern=val[0], field=val[1]))
        else:
            raise ValueError(
                f"Invalid observation spec for {key!r}: expected str or (pattern, field) tuple, "
                f"got {type(val).__name__}"
            )
    return specs


def _parse_action_spec(action: str | tuple[str, str]) -> _TopicSpec:
    if isinstance(action, str):
        return _TopicSpec(user_key="action", pattern=action, field=None)
    elif isinstance(action, tuple) and len(action) == 2:
        return _TopicSpec(user_key="action", pattern=action[0], field=action[1])
    else:
        raise ValueError(
            f"Invalid action spec: expected str or (pattern, field) tuple, "
            f"got {type(action).__name__}"
        )


def _normalize_sessions(sessions: list[Any]) -> list[str]:
    """Accept a list of SessionMetadata objects or plain session-ID strings."""
    ids = []
    for s in sessions:
        if isinstance(s, str):
            ids.append(s)
        elif hasattr(s, "id"):
            ids.append(s.id)
        else:
            raise TypeError(f"Expected str or SessionMetadata, got {type(s).__name__}")
    return ids


# ---------------------------------------------------------------------------
# Episode building
# ---------------------------------------------------------------------------

def _resolve_spec(client: DataClient, session_id: str, spec: _TopicSpec) -> str | None:
    """Resolve a topic spec's pattern to a single concrete topic."""
    if "*" not in spec.pattern:
        spec.resolved = spec.pattern
        return spec.pattern

    matched = client.match_topics(session_id, spec.pattern)
    if not matched:
        warnings.warn(f"No topics matched pattern {spec.pattern!r} in session {session_id}")
        return None
    if len(matched) > 1:
        warnings.warn(
            f"Pattern {spec.pattern!r} matched {len(matched)} topics in session {session_id}, "
            f"using first: {matched[0]!r}"
        )
    spec.resolved = matched[0]
    return matched[0]


def _detect_video(client: DataClient, session_id: str, spec: _TopicSpec) -> None:
    """Check if a string-only spec (no field) is a video topic."""
    if spec.field is not None:
        spec.is_video = False
        return
    try:
        idx = client.video_index(session_id, spec.resolved)
        spec.is_video = idx.frame_count > 0
    except Exception:
        spec.is_video = False


def _download_video(
    client: DataClient,
    session_id: str,
    topic: str,
    image_size: tuple[int, int] | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Download and decode video frames. Returns (data, timestamps)."""
    frames_list = []
    ts_list = []
    for frame in client.iter_frames(session_id, topic, size=image_size):
        frames_list.append(frame.image)
        ts_list.append(frame.timestamp)

    if not frames_list:
        return np.empty((0,), dtype=np.uint8), np.empty((0,), dtype=np.float64)

    data = np.stack(frames_list, axis=0)  # (N, H, W, 3)
    timestamps = np.array(ts_list, dtype=np.float64)
    return data, timestamps


def _download_records(
    client: DataClient,
    session_id: str,
    topic: str,
    field_name: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Download JSON records and extract a named field. Returns (data, timestamps)."""
    values = []
    ts_list = []
    for record in client.iter_records(session_id, topic):
        try:
            payload = json.loads(record.payload)
            val = payload[field_name]
            if isinstance(val, (list, tuple)):
                values.append(val)
            else:
                values.append([val])
            ts_list.append(record.timestamp)
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    if not values:
        return np.empty((0,), dtype=np.float32), np.empty((0,), dtype=np.float64)

    data = np.array(values, dtype=np.float32)  # (N, D)
    timestamps = np.array(ts_list, dtype=np.float64)
    return data, timestamps


def _build_episode(
    client: DataClient,
    session_id: str,
    obs_specs: list[_TopicSpec],
    action_spec: _TopicSpec,
    *,
    hz: float,
    image_size: tuple[int, int] | None,
) -> _Episode | None:
    """Download data for one session and build a resampled episode."""
    all_specs = list(obs_specs) + [action_spec]

    # 1. Resolve wildcards
    for spec in all_specs:
        if not _resolve_spec(client, session_id, spec):
            _log(f"  Skipping session {session_id}: could not resolve {spec.pattern!r}")
            return None

    # 2. Detect video for string-only specs
    for spec in obs_specs:
        _detect_video(client, session_id, spec)

    # 3. Download all topic data
    raw_data: dict[str, tuple[np.ndarray, np.ndarray]] = {}  # resolved → (data, ts)

    for spec in all_specs:
        if spec.resolved in raw_data:
            continue  # already downloaded (action may share a topic with obs)

        if spec.is_video:
            _log(f"  Downloading video: {spec.resolved}")
            raw_data[spec.resolved] = _download_video(
                client, session_id, spec.resolved, image_size,
            )
        elif spec.field is not None:
            _log(f"  Downloading records: {spec.resolved} (field={spec.field})")
            raw_data[spec.resolved] = _download_records(
                client, session_id, spec.resolved, spec.field,
            )
        else:
            # Raw bytes topic (non-video, no field) — skip for now
            _log(f"  Downloading raw records: {spec.resolved}")
            raw_data[spec.resolved] = _download_raw(
                client, session_id, spec.resolved,
            )

    # 4. Check all topics have data
    for spec in all_specs:
        data, ts = raw_data[spec.resolved]
        if len(ts) == 0:
            _log(f"  Skipping session {session_id}: no data for {spec.resolved}")
            return None

    # 5. Build resampled timeline
    # Find overlap range across all topics
    all_starts = [raw_data[s.resolved][1][0] for s in all_specs]
    all_ends = [raw_data[s.resolved][1][-1] for s in all_specs]
    t_start = max(all_starts)
    t_end = min(all_ends)

    if t_end <= t_start:
        _log(f"  Skipping session {session_id}: no time overlap across topics")
        return None

    target_ts = np.arange(t_start, t_end, 1.0 / hz)
    if len(target_ts) == 0:
        _log(f"  Skipping session {session_id}: resampled timeline is empty")
        return None

    # 6. Nearest-neighbour align each topic
    aligned: dict[str, np.ndarray] = {}
    for spec in all_specs:
        if spec.resolved in aligned:
            continue
        source_data, source_ts = raw_data[spec.resolved]
        idx = _align_ts(source_ts, target_ts)
        aligned[spec.resolved] = source_data[idx]

    _log(f"  Episode: {len(target_ts)} steps at {hz} Hz")
    return _Episode(session_id=session_id, length=len(target_ts), aligned=aligned)


def _download_raw(
    client: DataClient,
    session_id: str,
    topic: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Download raw record payloads as byte arrays. Returns (data, timestamps).

    Each payload is kept as raw bytes. The resulting data array is 1-D object array.
    """
    payloads = []
    ts_list = []
    for record in client.iter_records(session_id, topic):
        payloads.append(record.payload)
        ts_list.append(record.timestamp)

    if not payloads:
        return np.empty((0,), dtype=object), np.empty((0,), dtype=np.float64)

    data = np.array(payloads, dtype=object)
    timestamps = np.array(ts_list, dtype=np.float64)
    return data, timestamps


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(msg, file=sys.stderr)
