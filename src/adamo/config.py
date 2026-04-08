"""Backward-compatibility stub — use ``adamo.operate`` instead."""
from __future__ import annotations

import warnings as _warnings

_warnings.warn(
    "adamo.config is deprecated, use adamo.operate instead",
    DeprecationWarning,
    stacklevel=2,
)

from adamo.operate._config import connect, connect_async  # noqa: E402, F401
