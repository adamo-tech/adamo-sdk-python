"""Adamo session — thin wrapper around a Zenoh session with org-scoped key expressions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import zenoh
from zenoh import (
    CongestionControl,
    LivelinessToken,
    Priority,
    Publisher as ZPublisher,
    Reliability,
    Sample as ZSample,
    SampleKind,
    Session as ZSession,
    Subscriber as ZSubscriber,
)

if TYPE_CHECKING:
    from adamo._auth import ConnectionInfo


class Sample:
    """A received data sample."""

    __slots__ = ("key", "payload", "timestamp")

    def __init__(self, zenoh_sample: ZSample, prefix: str):
        full_key = str(zenoh_sample.key_expr)
        # Strip the adamo/{org}/ prefix so users see their own key expressions
        if full_key.startswith(prefix):
            self.key = full_key[len(prefix) :]
        else:
            self.key = full_key
        self.payload = bytes(zenoh_sample.payload)
        self.timestamp = zenoh_sample.timestamp

    def __repr__(self) -> str:
        size = len(self.payload)
        return f"Sample({self.key!r}, {size} bytes)"


class Publisher:
    """A persistent publisher for repeated puts to the same key expression."""

    def __init__(self, zenoh_publisher: ZPublisher):
        self._pub = zenoh_publisher

    def put(self, payload: bytes | str) -> None:
        if isinstance(payload, str):
            payload = payload.encode()
        self._pub.put(payload)

    def close(self) -> None:
        self._pub.undeclare()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Subscriber:
    """An iterator over received samples for a key expression."""

    def __init__(self, zenoh_subscriber: ZSubscriber, prefix: str):
        self._sub = zenoh_subscriber
        self._prefix = prefix

    def __iter__(self):
        return self

    def __next__(self) -> Sample:
        sample = self._sub.recv()
        return Sample(sample, self._prefix)

    def try_recv(self) -> Sample | None:
        sample = self._sub.try_recv()
        if sample is None:
            return None
        return Sample(sample, self._prefix)

    def close(self) -> None:
        self._sub.undeclare()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Session:
    """Adamo session — publish and subscribe to data through Adamo's Zenoh infrastructure.

    All key expressions are automatically prefixed with ``adamo/{org}/``
    unless ``raw=True`` is passed.
    """

    def __init__(self, zenoh_session: ZSession, info: ConnectionInfo):
        self._session = zenoh_session
        self._info = info
        self._prefix = f"adamo/{info.org}/"

    @property
    def org(self) -> str:
        return self._info.org

    @property
    def zenoh(self) -> ZSession:
        """Access the underlying Zenoh session directly."""
        return self._session

    def _resolve(self, key_expr: str, raw: bool = False) -> str:
        if raw:
            return key_expr
        return f"{self._prefix}{key_expr}"

    # -- Publish ---------------------------------------------------------------

    def put(
        self,
        key_expr: str,
        payload: bytes | str,
        *,
        raw: bool = False,
        priority: Priority = Priority.DATA,
        congestion_control: CongestionControl = CongestionControl.DROP,
        express: bool = False,
    ) -> None:
        """Publish a single value."""
        if isinstance(payload, str):
            payload = payload.encode()
        self._session.put(
            self._resolve(key_expr, raw),
            payload,
            priority=priority,
            congestion_control=congestion_control,
            express=express,
        )

    def publisher(
        self,
        key_expr: str,
        *,
        raw: bool = False,
        priority: Priority = Priority.DATA,
        congestion_control: CongestionControl = CongestionControl.DROP,
        reliability: Reliability = Reliability.BEST_EFFORT,
        express: bool = False,
    ) -> Publisher:
        """Declare a persistent publisher for repeated puts."""
        pub = self._session.declare_publisher(
            self._resolve(key_expr, raw),
            priority=priority,
            congestion_control=congestion_control,
            reliability=reliability,
            express=express,
        )
        return Publisher(pub)

    # -- Subscribe -------------------------------------------------------------

    def subscribe(
        self,
        key_expr: str,
        *,
        raw: bool = False,
        callback: Callable[[Sample], None] | None = None,
    ) -> Subscriber:
        """Subscribe to a key expression. Returns an iterable of Samples.

        If ``callback`` is provided, samples are delivered to the callback
        instead and the returned Subscriber is used only for lifecycle (close).
        """
        resolved = self._resolve(key_expr, raw)
        prefix = self._prefix

        if callback is not None:

            def _handler(s: ZSample):
                callback(Sample(s, prefix))

            sub = self._session.declare_subscriber(resolved, _handler)
        else:
            sub = self._session.declare_subscriber(resolved)

        return Subscriber(sub, prefix)

    # -- Query -----------------------------------------------------------------

    def get(
        self,
        key_expr: str,
        *,
        raw: bool = False,
        timeout_ms: int = 5000,
    ) -> list[Sample]:
        """One-shot query for data matching a key expression."""
        resolved = self._resolve(key_expr, raw)
        replies = self._session.get(
            resolved,
            timeout=timeout_ms / 1000.0,
        )
        results = []
        for reply in replies:
            sample = reply.ok
            if sample is not None:
                results.append(Sample(sample, self._prefix))
        return results

    # -- Liveliness ------------------------------------------------------------

    def alive(self, token_key: str) -> LivelinessToken:
        """Declare this client as alive. The token stays alive until dropped.

        Publishes liveliness at ``adamo/{org}/{token_key}/alive``.
        """
        key = f"{self._prefix}{token_key}/alive"
        return self._session.liveliness().declare_token(key)

    def live_tokens(self, pattern: str = "**/alive") -> list[str]:
        """Query currently live tokens matching a pattern within this org."""
        resolved = f"{self._prefix}{pattern}"
        replies = self._session.liveliness().get(resolved)
        tokens = []
        for reply in replies:
            sample = reply.ok
            if sample is not None:
                full_key = str(sample.key_expr)
                if full_key.startswith(self._prefix):
                    tokens.append(full_key[len(self._prefix) :])
                else:
                    tokens.append(full_key)
        return tokens

    def on_liveliness(
        self,
        pattern: str = "**/alive",
        *,
        callback: Callable[[str, bool], None] | None = None,
        history: bool = True,
    ) -> ZSubscriber:
        """Watch for liveliness changes within this org.

        ``callback(key, is_alive)`` is called when a token appears or disappears.
        """
        resolved = f"{self._prefix}{pattern}"
        prefix = self._prefix

        def _handler(s: ZSample):
            full_key = str(s.key_expr)
            if full_key.startswith(prefix):
                key = full_key[len(prefix) :]
            else:
                key = full_key
            is_alive = s.kind == SampleKind.PUT
            if callback:
                callback(key, is_alive)

        return self._session.liveliness().declare_subscriber(
            resolved, _handler, history=history
        )

    # -- Lifecycle -------------------------------------------------------------

    def close(self) -> None:
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
