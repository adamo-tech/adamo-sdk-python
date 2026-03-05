"""Test round-trip pub/sub through Adamo's Zenoh routers.

Usage:
    python test_roundtrip.py <api_key>
"""

import sys
import threading
import time

import adamo


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <api_key>")
        sys.exit(1)

    api_key = sys.argv[1]

    print("Connecting to Adamo...")
    session = adamo.connect(api_key=api_key)
    print(f"Connected (org: {session.org})")

    received = []
    key = "test/roundtrip"

    # Subscribe in a background thread
    sub = session.subscribe(key, callback=lambda s: received.append(s))
    print(f"Subscribed to {key}")

    # Give the subscriber time to propagate
    time.sleep(1)

    # Publish a few messages
    n = 5
    print(f"Publishing {n} messages...")
    for i in range(n):
        session.put(key, f"hello-{i}".encode())
        time.sleep(0.1)

    # Wait for messages to arrive
    time.sleep(2)

    print(f"\nReceived {len(received)}/{n} messages:")
    for s in received:
        print(f"  {s.key} => {s.payload.decode()}")

    # Test liveliness
    print("\nDeclaring liveliness token...")
    token = session.alive("test-robot")
    time.sleep(1)

    live = session.live_tokens()
    print(f"Live tokens: {live}")

    # Cleanup
    sub.close()
    session.close()

    if len(received) == n:
        print("\nAll messages received — round-trip OK")
    else:
        print(f"\nOnly {len(received)}/{n} messages received")
        sys.exit(1)


if __name__ == "__main__":
    main()
