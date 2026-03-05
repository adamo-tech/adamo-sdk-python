"""Backward-compatibility stub — use ``adamo.operate.session`` instead."""

import warnings as _warnings

_warnings.warn(
    "adamo.session is deprecated, use adamo.operate.session instead",
    DeprecationWarning,
    stacklevel=2,
)

from adamo.operate.session import (  # noqa: E402, F401
    Sample,
    Publisher,
    Subscriber,
    Session,
)
