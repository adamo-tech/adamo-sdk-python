"""Listen for control messages from Adamo."""

import adamo
from adamo.operate.control import JointState, Joy, decode_control

session = adamo.connect(api_key="ak_your_key_here")

with session.subscribe("my-robot/control/**") as sub:
    for sample in sub:
        msg = decode_control(sample.payload)
        if isinstance(msg, JointState):
            print(f"JointState: {msg.positions}")
        elif isinstance(msg, Joy):
            print(f"Joy: axes={msg.axes} buttons={msg.buttons}")
        else:
            print(f"Unknown: {msg}")
