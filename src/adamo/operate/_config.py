"""Connect to Adamo — authenticate and open a Zenoh session."""

from __future__ import annotations

import json
from typing import Literal, cast

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

_ZENOH_PROTOCOLS = ("quic", "udp", "tcp")
ZenohProtocol = Literal["quic", "udp", "tcp"]


def _validate_protocol(protocol: str) -> ZenohProtocol:
    if protocol not in _ZENOH_PROTOCOLS:
        allowed = ", ".join(repr(p) for p in _ZENOH_PROTOCOLS)
        raise ValueError(f"protocol must be one of {allowed}, got {protocol!r}")
    return cast(ZenohProtocol, protocol)


def _zenoh_connect_endpoint(info: ConnectionInfo, protocol: ZenohProtocol) -> str:
    if protocol == "quic":
        return info.quic_endpoint
    if protocol == "udp":
        if not info.udp_endpoint:
            raise ValueError("UDP endpoint missing from connection config")
        return info.udp_endpoint
    # tcp — derive from UDP URL (same rule as adamohq/adamo-network)
    if "udp/" not in info.udp_endpoint:
        raise ValueError(
            "Cannot derive TCP endpoint: UDP URL does not contain 'udp/'"
        )
    return info.udp_endpoint.replace("udp/", "tcp/", 1)


def _build_zenoh_config(info: ConnectionInfo, protocol: ZenohProtocol) -> zenoh.Config:
    """Build a Zenoh client config targeting the Adamo router."""
    endpoint = _zenoh_connect_endpoint(info, protocol)
    config = zenoh.Config()
    config.insert_json5("mode", json.dumps("client"))
    config.insert_json5("connect/endpoints", json.dumps([endpoint]))
    return config


def connect(
    *,
    api_key: str | None = None,
    token: str | None = None,
    org_id: str | None = None,
    api_url: str = DEFAULT_API_URL,
    protocol: ZenohProtocol = "quic",
) -> Session:
    """Connect to Adamo and return a Session.

    Provide exactly one of ``api_key`` or ``token``.

    Args:
        api_key: An Adamo API key (``ak_...``). Used for robots and scripts.
        token: A Supabase JWT token. Used for user-authenticated sessions.
        org_id: Organization ID (only used with ``token``).
        api_url: Override the Adamo API base URL.
        protocol: Zenoh transport to the cloud router: ``\"quic\"`` (default),
            ``\"udp\"``, or ``\"tcp\"``. QUIC matches existing behavior. UDP uses
            the API ``adamo_udp_url``; TCP is derived from that URL by replacing
            ``udp/`` with ``tcp/``. On restrictive networks, UDP may be blocked
            by firewalls or NAT; TCP or QUIC may be more reliable.

    Returns:
        A connected :class:`Session`.
    """
    p = _validate_protocol(protocol)
    info = _resolve_auth(api_key=api_key, token=token, org_id=org_id, api_url=api_url)
    config = _build_zenoh_config(info, p)
    zenoh_session = zenoh.open(config)
    return Session(zenoh_session, info)


async def connect_async(
    *,
    api_key: str | None = None,
    token: str | None = None,
    org_id: str | None = None,
    api_url: str = DEFAULT_API_URL,
    protocol: ZenohProtocol = "quic",
) -> Session:
    """Async version of :func:`connect`.

    The Zenoh session itself is synchronous (the Python binding doesn't expose
    an async open), but the API config fetch is done asynchronously.

    Accepts the same arguments as :func:`connect`, including ``protocol``.
    """
    p = _validate_protocol(protocol)
    info = await _resolve_auth_async(
        api_key=api_key, token=token, org_id=org_id, api_url=api_url
    )
    config = _build_zenoh_config(info, p)
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
