"""Subscribe with a callback instead of iterating."""

import time

import adamo

session = adamo.connect(api_key="ak_your_key_here")


def on_data(sample: adamo.Session):
    print(f"Received: {sample.key} ({len(sample.payload)} bytes)")


sub = session.subscribe("my-robot/**", callback=on_data)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    sub.close()
    session.close()
