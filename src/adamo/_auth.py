"""Authenticate with the Adamo API and retrieve Zenoh connection config."""

from __future__ import annotations

import time as _time
from dataclasses import dataclass

import httpx

API_BASE = "https://q14iirks46.execute-api.eu-west-2.amazonaws.com"
STORE_BASE = "https://store.adamohq.com"


@dataclass(frozen=True)
class ConnectionInfo:
    org: str
    quic_endpoint: str
    udp_endpoint: str
    wss_endpoint: str


@dataclass(frozen=True)
class TokenInfo:
    """Short-lived JWT obtained by exchanging an API key."""

    token: str
    org_id: str
    org_slug: str
    expires_at: int  # unix timestamp

    @property
    def expired(self) -> bool:
        """True if the token has expired (with 60 s safety buffer)."""
        return _time.time() >= (self.expires_at - 60)


def fetch_config_api_key(api_key: str, *, api_url: str = API_BASE) -> ConnectionInfo:
    """Fetch connection config using an API key (no user auth required)."""
    resp = httpx.get(
        f"{api_url}/api/keys/config",
        headers={"X-API-Key": api_key},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return ConnectionInfo(
        org=data["org"],
        quic_endpoint=data["adamo_quic_url"],
        udp_endpoint=data["adamo_udp_url"],
        wss_endpoint=data["adamo_url"],
    )


async def fetch_config_api_key_async(
    api_key: str, *, api_url: str = API_BASE
) -> ConnectionInfo:
    """Async version of fetch_config_api_key."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{api_url}/api/keys/config",
            headers={"X-API-Key": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    return ConnectionInfo(
        org=data["org"],
        quic_endpoint=data["adamo_quic_url"],
        udp_endpoint=data["adamo_udp_url"],
        wss_endpoint=data["adamo_url"],
    )


def fetch_config_token(
    token: str, *, org_id: str | None = None, api_url: str = API_BASE
) -> ConnectionInfo:
    """Fetch connection config using a Supabase JWT token."""
    params = {}
    if org_id:
        params["org_id"] = org_id
    resp = httpx.get(
        f"{api_url}/api/zenoh/endpoint",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return ConnectionInfo(
        org=data["org_slug"],
        quic_endpoint=data["quic_endpoint"],
        udp_endpoint=data["udp_endpoint"],
        wss_endpoint=data["wss_endpoint"],
    )


async def fetch_config_token_async(
    token: str, *, org_id: str | None = None, api_url: str = API_BASE
) -> ConnectionInfo:
    """Async version of fetch_config_token."""
    params = {}
    if org_id:
        params["org_id"] = org_id
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{api_url}/api/zenoh/endpoint",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    return ConnectionInfo(
        org=data["org_slug"],
        quic_endpoint=data["quic_endpoint"],
        udp_endpoint=data["udp_endpoint"],
        wss_endpoint=data["wss_endpoint"],
    )


def exchange_api_key_for_token(
    api_key: str, *, api_url: str = API_BASE
) -> TokenInfo:
    """Exchange an API key for a short-lived JWT."""
    resp = httpx.post(
        f"{api_url}/api/keys/token",
        headers={"X-API-Key": api_key},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return TokenInfo(
        token=data["token"],
        org_id=data["org_id"],
        org_slug=data["org_slug"],
        expires_at=data["expires_at"],
    )


async def exchange_api_key_for_token_async(
    api_key: str, *, api_url: str = API_BASE
) -> TokenInfo:
    """Async version of exchange_api_key_for_token."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{api_url}/api/keys/token",
            headers={"X-API-Key": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    return TokenInfo(
        token=data["token"],
        org_id=data["org_id"],
        org_slug=data["org_slug"],
        expires_at=data["expires_at"],
    )
