"""Smoke test: synthetic video + continuous robot.log() stream.

Run this then open the web Operate page for the robot. Expand the
bottom panel — log lines should tick in once per second.
"""
import threading
import time

import numpy as np

import adamo

API_KEY = "ak_2M3T7rqPYGubJO2gBsxRoWswKn83z0L6"
NAME = "macbook"
WIDTH, HEIGHT, FPS = 1280, 720, 30

robot = adamo.Robot(api_key=API_KEY, name=NAME)
track = robot.video(
    "synthetic",
    width=WIDTH,
    height=HEIGHT,
    pixel_format="BGRA",
    bitrate_kbps=4000,
    fps=FPS,
)


def log_loop():
    """Publish a log line every second until Ctrl+C."""
    samples = [
        ("info", "heartbeat"),
        ("debug", "encoder in steady state"),
        ("info", "frame {n} delivered"),
        ("warn", "jitter above threshold"),
        ("error", "simulated transient"),
        ("info", "recovered"),
    ]
    i = 0
    # Let the session/video come up first.
    time.sleep(1.5)
    while True:
        level, msg = samples[i % len(samples)]
        robot.log(msg.format(n=i), level=level)
        print(f"[{level:5}] {msg.format(n=i)}")
        i += 1
        time.sleep(1.0)


threading.Thread(target=log_loop, daemon=True, name="log-loop").start()

print(f"Pushing {WIDTH}x{HEIGHT} BGRA @ {FPS}fps  + logs every 1s")
print("Open http://localhost:5173 → /operate/macbook, expand the bottom panel.")
print("Ctrl+C to stop.")

frame = np.zeros((HEIGHT, WIDTH, 4), dtype=np.uint8)
frame[..., 3] = 255

xs = np.tile(np.arange(WIDTH, dtype=np.uint8), (HEIGHT, 1))
ys = np.tile(np.arange(HEIGHT, dtype=np.uint8)[:, None], (1, WIDTH))

count = 0
start = time.monotonic()
interval = 1.0 / FPS

try:
    while True:
        t = np.uint8(count & 0xFF)
        frame[..., 0] = xs + t
        frame[..., 1] = ys + np.uint8((count * 2) & 0xFF)
        frame[..., 2] = ((xs.astype(np.uint16) + ys + count * 3) >> 1).astype(np.uint8)

        track.send(frame)

        count += 1
        next_t = start + count * interval
        sleep = next_t - time.monotonic()
        if sleep > 0:
            time.sleep(sleep)
except KeyboardInterrupt:
    print("\nStopping.")
