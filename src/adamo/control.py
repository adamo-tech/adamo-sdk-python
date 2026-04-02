"""Backward-compatibility stub — use ``adamo.operate.control`` instead."""

import warnings as _warnings

_warnings.warn(
    "adamo.control is deprecated, use adamo.operate.control instead",
    DeprecationWarning,
    stacklevel=2,
)

from adamo.operate.control import (  # noqa: E402, F401
    JointState,
    Joy,
    JoystickCommand,
    decode_control,
)
