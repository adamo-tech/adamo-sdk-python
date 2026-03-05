"""Discover live robots and watch for changes."""

import time

import adamo

session = adamo.connect(api_key="ak_your_key_here")

# Declare this client as alive
token = session.alive("my-robot")

# Query currently alive robots
live = session.live_tokens()
print("Currently alive:", live)

# Watch for robots joining/leaving
sub = session.on_liveliness(
    callback=lambda key, is_alive: print(
        f"{'JOINED' if is_alive else 'LEFT'}: {key}"
    )
)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    sub.undeclare()
    session.close()
