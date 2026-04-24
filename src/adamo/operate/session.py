"""Adamo session — wraps the native CoreSession with org-scoped key expressions.

The public API (put / publisher / subscribe / get / alive / live_tokens /
on_liveliness) is identical to the previous eclipse-zenoh-backed version —
only the implementation moved from `import zenoh` to `adamo._native.CoreSession`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from adamo._auth import ConnectionInfo
    from adamo._native import (
        CoreSession,
        CorePublisher,
        CoreSubscriber,
        CoreCallbackSubscriber,
        CoreLivelinessToken,
        CoreSample,
    )


# Priority constants — legacy API exposed an `adamo.Priority` analogous to
# `zenoh.Priority`. CoreSession uses a u8 0-255 scale (higher = more
# important). These names are kept for API compatibility; each is the u8
# value that `priority_from_u8` maps into the matching zenoh class.
class Priority:
    REAL_TIME = 250
    INTERACTIVE_HIGH = 220
    INTERACTIVE_LOW = 190
    DATA_HIGH = 150
    DATA = 100
    DATA_LOW = 80
    BACKGROUND = 20


class Sample:
    """A received data sample."""

    __slots__ = ("key", "payload", "timestamp")

    def __init__(self, core_sample: "CoreSample", prefix: str):
        full_key = core_sample.key
        if full_key.startswith(prefix):
            self.key = full_key[len(prefix) :]
        else:
            self.key = full_key
        self.payload = core_sample.payload
        # CoreSample doesn't expose timestamp yet; set to None.
        self.timestamp = None

    def __repr__(self) -> str:
        size = len(self.payload)
        return f"Sample({self.key!r}, {size} bytes)"


class Publisher:
    """A persistent publisher for repeated puts to the same key expression."""

    def __init__(self, core_publisher: "CorePublisher"):
        self._pub = core_publisher

    def put(self, payload: bytes | str) -> None:
        if isinstance(payload, str):
            payload = payload.encode()
        self._pub.put(payload)

    def close(self) -> None:
        self._pub.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Subscriber:
    """An iterator over received samples (polling form)."""

    def __init__(self, core_sub: "CoreSubscriber", prefix: str):
        self._sub = core_sub
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
        self._sub.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class CallbackSubscriber:
    """Subscriber lifecycle handle for callback-based subscribe()."""

    def __init__(self, core_sub: "CoreCallbackSubscriber"):
        self._sub = core_sub

    def close(self) -> None:
        self._sub.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class LivelinessToken:
    """A liveliness token — alive until close() or garbage collection."""

    def __init__(self, core_token: "CoreLivelinessToken"):
        self._token = core_token

    def close(self) -> None:
        self._token.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Session:
    """Adamo session — publish and subscribe to data through Adamo's Zenoh infrastructure.

    Keys are scoped to the session's org namespace.
    """

    def __init__(self, core_session: "CoreSession", info: ConnectionInfo):
        self._session = core_session
        self._info = info
        self._prefix = f"adamo/{info.org}/"
        # Keep callback subscribers alive so their zenoh undeclare handles
        # aren't dropped the moment the user stops holding the return value.
        self._callback_subs: list[CallbackSubscriber] = []

    @property
    def org(self) -> str:
        return self._info.org

    def _resolve(self, key_expr: str, raw: bool = False) -> str:
        return key_expr

    # -- Publish ---------------------------------------------------------------

    def put(
        self,
        key_expr: str,
        payload: bytes | str,
        *,
        raw: bool = False,
        priority: int = Priority.DATA,
        express: bool = False,
        reliable: bool = False,
    ) -> None:
        """Publish a single value."""
        if isinstance(payload, str):
            payload = payload.encode()
        self._session.put(
            self._resolve(key_expr, raw),
            payload,
            priority=int(priority),
            express=express,
            reliable=reliable,
        )

    def publisher(
        self,
        key_expr: str,
        *,
        raw: bool = False,
        priority: int = Priority.DATA,
        express: bool = False,
        reliable: bool = False,
    ) -> Publisher:
        """Declare a persistent publisher for repeated puts."""
        core_pub = self._session.publisher(
            self._resolve(key_expr, raw),
            priority=int(priority),
            express=express,
            reliable=reliable,
        )
        return Publisher(core_pub)

    # -- Subscribe -------------------------------------------------------------

    def subscribe(
        self,
        key_expr: str,
        *,
        raw: bool = False,
        callback: Callable[[Sample], None] | None = None,
    ) -> Subscriber | CallbackSubscriber:
        """Subscribe to a key expression.

        Without ``callback``: returns a :class:`Subscriber` you iterate or
        poll via ``.try_recv()``.

        With ``callback``: the callback is invoked on the zenoh receive
        thread each time a sample arrives. Returns a lifecycle
        :class:`CallbackSubscriber` (call ``close()`` to stop). The
        Session also holds a strong reference internally so the handle
        isn't GC'd while samples are still expected.
        """
        resolved = self._resolve(key_expr, raw)
        prefix = self._prefix

        if callback is None:
            core_sub = self._session.subscribe(resolved)
            return Subscriber(core_sub, prefix)

        def _wrap(core_sample) -> None:
            callback(Sample(core_sample, prefix))

        core_sub = self._session.subscribe_callback(resolved, _wrap)
        handle = CallbackSubscriber(core_sub)
        self._callback_subs.append(handle)
        return handle

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
        core_samples = self._session.get(resolved, timeout_ms=timeout_ms)
        return [Sample(s, self._prefix) for s in core_samples]

    # -- Liveliness ------------------------------------------------------------

    def alive(self, token_key: str) -> LivelinessToken:
        """Declare this client alive at ``{token_key}/alive``.

        The token stays alive until close() or garbage collection.
        """
        return LivelinessToken(self._session.alive(token_key))

    def live_tokens(self, pattern: str = "**/alive") -> list[str]:
        """Query currently live tokens matching a pattern within this org."""
        return self._session.live_tokens(pattern)

    def on_liveliness(
        self,
        pattern: str = "**/alive",
        *,
        callback: Callable[[str, bool], None] | None = None,
        history: bool = True,
    ) -> CallbackSubscriber:
        """Watch for liveliness changes within this org.

        ``callback(key, is_alive)`` fires when a token appears or disappears.
        """
        if callback is None:
            raise ValueError("on_liveliness requires callback=")
        core_sub = self._session.on_liveliness(callback, pattern, history)
        handle = CallbackSubscriber(core_sub)
        self._callback_subs.append(handle)
        return handle

    # -- Lifecycle -------------------------------------------------------------

    def close(self) -> None:
        for sub in self._callback_subs:
            try:
                sub.close()
            except Exception:
                pass
        self._callback_subs.clear()
        # CoreSession is dropped by Python GC; no explicit close needed
        # (the underlying zenoh::Session is Arc'd and released when the
        # last handle drops).

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
