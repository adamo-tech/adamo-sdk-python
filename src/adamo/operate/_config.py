"""Connect to Adamo — authenticate and open a Zenoh session."""

from __future__ import annotations

import json

import zenoh

from adamo._auth import (
    ConnectionInfo,
    fetch_config_api_key,
    fetch_config_api_key_async,
    fetch_config_token,
    fetch_config_token_async,
)
from adamo.operate.session import Session

DEFAULT_API_URL = "https://q14iirks46.execute-api.eu-west-2.amazonaws.com"


def _build_zenoh_config(info: ConnectionInfo) -> zenoh.Config:
    """Build a Zenoh Config targeting the Adamo router via QUIC."""
    config = zenoh.Config()
    config.insert_json5("mode", json.dumps("client"))
    config.insert_json5(
        "connect/endpoints", json.dumps([info.quic_endpoint])
    )
    return config


def connect(
    *,
    api_key: str | None = None,
    token: str | None = None,
    org_id: str | None = None,
    api_url: str = DEFAULT_API_URL,
) -> Session:
    """Connect to Adamo and return a Session.

    Provide exactly one of ``api_key`` or ``token``.

    Args:
        api_key: An Adamo API key (``ak_...``). Used for robots and scripts.
        token: A Supabase JWT token. Used for user-authenticated sessions.
        org_id: Organization ID (only used with ``token``).
        api_url: Override the Adamo API base URL.

    Returns:
        A connected :class:`Session`.
    """
    info = _resolve_auth(api_key=api_key, token=token, org_id=org_id, api_url=api_url)
    config = _build_zenoh_config(info)
    zenoh_session = zenoh.open(config)
    return Session(zenoh_session, info)


async def connect_async(
    *,
    api_key: str | None = None,
    token: str | None = None,
    org_id: str | None = None,
    api_url: str = DEFAULT_API_URL,
) -> Session:
    """Async version of :func:`connect`.

    The Zenoh session itself is synchronous (the Python binding doesn't expose
    an async open), but the API config fetch is done asynchronously.
    """
    info = await _resolve_auth_async(
        api_key=api_key, token=token, org_id=org_id, api_url=api_url
    )
    config = _build_zenoh_config(info)
    zenoh_session = zenoh.open(config)
    return Session(zenoh_session, info)


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
