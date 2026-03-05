"""Listen for GELLO joint positions from Adamo.

Usage:
    pip install adamo
    python gello_subscribe.py
"""

import json

import adamo

session = adamo.connect(api_key="ak_your_key_here")

with session.subscribe("my-robot/control/**") as sub:
    for sample in sub:
        msg = json.loads(sample.payload)
        print(msg["positions"])
