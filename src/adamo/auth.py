"""Backward-compatibility stub — use ``adamo._auth`` directly."""

import warnings as _warnings

_warnings.warn(
    "adamo.auth is deprecated, import from adamo._auth instead",
    DeprecationWarning,
    stacklevel=2,
)

from adamo._auth import (  # noqa: E402, F401
    API_BASE,
    ConnectionInfo,
    TokenInfo,
    fetch_config_api_key,
    fetch_config_api_key_async,
    fetch_config_token,
    fetch_config_token_async,
    exchange_api_key_for_token,
    exchange_api_key_for_token_async,
)
