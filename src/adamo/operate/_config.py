"""Connect to Adamo — authenticate and open a Zenoh session via _native."""

from __future__ import annotations

from adamo._auth import (
    ConnectionInfo,
    fetch_config_api_key,
    fetch_config_api_key_async,
    fetch_config_token,
    fetch_config_token_async,
)
from adamo._native import open_core, open_core_mtls
from adamo.operate.session import Session

DEFAULT_API_URL = "https://q14iirks46.execute-api.eu-west-2.amazonaws.com"


def connect(
    *,
    api_key: str | None = None,
    token: str | None = None,
    org_id: str | None = None,
    api_url: str = DEFAULT_API_URL,
    protocol: str = "quic",
    mtls: bool = False,
) -> Session:
    """Connect to Adamo and return a Session.

    Provide exactly one of ``api_key`` or ``token``.

    Args:
        api_key: An Adamo API key (``ak_...``). Used for robots and scripts.
        token: A Supabase JWT token. Used for user-authenticated sessions.
        org_id: Organization ID (only used with ``token``).
        api_url: Override the Adamo API base URL.
        protocol: Transport protocol — ``"quic"`` (default), ``"udp"``, or ``"tcp"``.
        mtls: When True (and using ``api_key``), mint a per-user mTLS client
            cert from ``/api/zenoh/cert`` and present it on the Zenoh QUIC
            handshake. Required once routers enforce mTLS.

    Returns:
        A connected :class:`Session`.
    """
    info = _resolve_auth(api_key=api_key, token=token, org_id=org_id, api_url=api_url)
    if api_key is None:
        raise NotImplementedError(
            "token-based connect via _native is not yet wired; pass api_key= for now"
        )
    core = open_core_mtls(api_key, protocol) if mtls else open_core(api_key, protocol)
    return Session(core, info)


async def connect_async(
    *,
    api_key: str | None = None,
    token: str | None = None,
    org_id: str | None = None,
    api_url: str = DEFAULT_API_URL,
    protocol: str = "quic",
    mtls: bool = False,
) -> Session:
    """Async version of :func:`connect`.

    The zenoh session itself opens synchronously inside _native; only the API
    config fetch runs asynchronously.
    """
    info = await _resolve_auth_async(
        api_key=api_key, token=token, org_id=org_id, api_url=api_url
    )
    if api_key is None:
        raise NotImplementedError(
            "token-based connect via _native is not yet wired; pass api_key= for now"
        )
    core = open_core_mtls(api_key, protocol) if mtls else open_core(api_key, protocol)
    return Session(core, info)


def _resolve_auth(
    *,
    api_key: str | None,
    token: str | None,
    org_id: str | None,
    api_url: str,
) -> ConnectionInfo:
    if api_key and token:
        raise ValueError("Provide either api_key or token, not both")
    if api_key:
        return fetch_config_api_key(api_key, api_url=api_url)
    if token:
        return fetch_config_token(token, org_id=org_id, api_url=api_url)
    raise ValueError("Must provide either api_key or token")


async def _resolve_auth_async(
    *,
    api_key: str | None,
    token: str | None,
    org_id: str | None,
    api_url: str,
) -> ConnectionInfo:
    if api_key and token:
        raise ValueError("Provide either api_key or token, not both")
    if api_key:
        return await fetch_config_api_key_async(api_key, api_url=api_url)
    if token:
        return await fetch_config_token_async(token, org_id=org_id, api_url=api_url)
    raise ValueError("Must provide either api_key or token")
