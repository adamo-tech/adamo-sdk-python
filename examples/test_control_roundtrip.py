"""Test: publish a JointState and receive it back over Adamo's Zenoh network."""

import sys
import threading
import time

import adamo
from adamo.operate.control import JointState, decode_control

API_KEY = sys.argv[1] if len(sys.argv) > 1 else "ak_your_key_here"
ROBOT = "test-gello"
TOPIC = "joint_states"

received = []


def listener(session: adamo.Session):
    with session.subscribe(f"{ROBOT}/control/json/{TOPIC}") as sub:
        for sample in sub:
            msg = decode_control(sample.payload)
            received.append(msg)
            print(f"  <- received: {msg}")
            if len(received) >= 3:
                return


print("Connecting to Adamo...")
session = adamo.connect(api_key=API_KEY)
print(f"Connected (org={session.org})")

# Start listener in background thread
t = threading.Thread(target=listener, args=(session,), daemon=True)
t.start()

# Give subscriber time to propagate
time.sleep(1.0)

# Publish 3 messages
print("Publishing 3 JointState messages...")
with session.publisher(f"{ROBOT}/control/json/{TOPIC}") as pub:
    for i in range(3):
        js = JointState(
            names=["j1", "j2", "j3", "j4", "j5", "j6", "j7"],
            positions=[0.1 * (i + 1)] * 7,
        )
        pub.put(js.to_json())
        print(f"  -> sent positions={js.positions}")
        time.sleep(0.1)

# Wait for listener to receive
t.join(timeout=5.0)

if len(received) == 3:
    print(f"\nSUCCESS: received {len(received)}/3 messages")
    for i, msg in enumerate(received):
        assert isinstance(msg, JointState), f"Expected JointState, got {type(msg)}"
        assert len(msg.positions) == 7
        print(f"  [{i}] positions={msg.positions}")
else:
    print(f"\nFAIL: received {len(received)}/3 messages")

session.close()
