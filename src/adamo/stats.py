"""Latency / network-stats helpers.

Adamo robots publish a 1 Hz heartbeat carrying a GARCH-based forecast of
the current network regime, and echo a ping/pong topic for round-trip
probing. This module exposes both as typed Python APIs so callers don't
have to know the wire format.

Use :meth:`Robot.watch_latency` to stream :class:`LatencyStats` from a
robot, and :meth:`Robot.measure_rtt` for a one-shot RTT probe.
"""
from __future__ import annotations

import enum
import json
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from adamo.session import Robot
    from adamo.operate.session import Session


class Regime(enum.IntEnum):
    """Network regime as classified by the robot's GARCH forecaster."""
    STABLE = 0
    DEGRADING = 1
    VOLATILE = 2
    RECOVERING = 3


@dataclass(frozen=True)
class LatencyStats:
    """One latency snapshot from a robot's heartbeat."""
    regime: Regime
    jitter_hint_ms: float
    garch_sigma_ms: float
    target_bitrate_kbps: int
    loss_rate: float
    queuing_delay_ms: float
    timestamp_ms: int

    @classmethod
    def parse(cls, payload: bytes) -> "LatencyStats | None":
        """Parse a heartbeat payload. Returns None on the very first
        heartbeat (before the forecast loop has produced its first
        sample) or if the payload isn't valid JSON.
        """
        try:
            obj = json.loads(payload)
        except (ValueError, TypeError):
            return None
        forecast = obj.get("forecast") if isinstance(obj, dict) else None
        if not isinstance(forecast, dict):
            return None
        return cls(
            regime=Regime(int(forecast.get("regime", 0))),
            jitter_hint_ms=float(forecast.get("jitter_hint_ms", 0.0)),
            garch_sigma_ms=float(forecast.get("garch_sigma_ms", 0.0)),
            target_bitrate_kbps=int(forecast.get("target_bitrate_kbps", 0)),
            loss_rate=float(forecast.get("loss_rate", 0.0)),
            queuing_delay_ms=float(forecast.get("queuing_delay_ms", 0.0)),
            timestamp_ms=int(obj.get("timestamp", 0)),
        )


def heartbeat_topic(robot: str) -> str:
    """Topic carrying :class:`LatencyStats` for ``robot``."""
    return f"{robot}/heartbeat"


def ping_topic(robot: str) -> str:
    """Topic the SDK puts ping payloads on."""
    return f"{robot}/stats/ping"


def pong_topic(robot: str) -> str:
    """Topic the robot echoes ping payloads back on."""
    return f"{robot}/stats/pong"


def watch_latency(
    robot: "Robot | Session",
    name: str,
    callback: Callable[[LatencyStats], None],
):
    """Subscribe to ``name``'s heartbeat and invoke ``callback`` with each
    parsed :class:`LatencyStats`. Heartbeats with no forecast block yet
    are silently dropped. Returns the underlying subscriber handle —
    keep it alive (or call ``.close()``) to control the subscription.
    """
    def _handler(sample):
        stats = LatencyStats.parse(sample.payload)
        if stats is not None:
            callback(stats)

    session = getattr(robot, "session", robot)
    return session.subscribe(heartbeat_topic(name), raw=True, callback=_handler)


def measure_rtt(robot: "Robot | Session", name: str, timeout: float = 1.0) -> float:
    """One-shot round-trip-time probe. Publishes a 4-byte nonce on
    ``ping_topic(name)`` and blocks until the matching pong returns or
    ``timeout`` seconds elapse (raises :class:`TimeoutError`).

    Returns the measured RTT in seconds.
    """
    session = getattr(robot, "session", robot)
    nonce = os.urandom(4)
    sub = session.subscribe(pong_topic(name), raw=True)
    try:
        start = time.monotonic()
        session.put(ping_topic(name), nonce, raw=True, express=True)
        deadline = start + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"measure_rtt({name!r}): no pong within {timeout}s")
            sample = sub.try_recv()
            if sample is None:
                # Brief sleep to avoid busy-spin; the pong path is sub-ms
                # so this still resolves promptly.
                time.sleep(min(0.001, remaining))
                continue
            payload = sample.payload
            if len(payload) >= 4 and payload[:4] == nonce:
                return time.monotonic() - start
    finally:
        sub.close()
