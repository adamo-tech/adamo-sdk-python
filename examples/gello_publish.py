"""Publish GELLO joint positions to Adamo.

Replace get_joint_positions() with your Dynamixel driver read.

Usage:
    pip install adamo
    python gello_publish.py
"""

import json
import time

import adamo

JOINT_NAMES = ["j1", "j2", "j3", "j4", "j5", "j6", "j7"]


def get_joint_positions() -> list[float]:
    """Stub — replace with your Dynamixel read."""
    return [0.0] * len(JOINT_NAMES)


session = adamo.connect(api_key="ak_your_key_here")

with session.publisher("my-robot/control/json/joint_states") as pub:
    while True:
        msg = json.dumps({
            "names": JOINT_NAMES,
            "positions": get_joint_positions(),
        }).encode()
        pub.put(msg)
        time.sleep(0.01)
