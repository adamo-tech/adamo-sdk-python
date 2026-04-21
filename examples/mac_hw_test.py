"""Smoke test: synthetic frames → Mac VideoToolbox encoder → Zenoh.

Generates a moving BGRA gradient at 30fps and pushes it through
robot.video() → iceoryx2 SHM → Rust vtenc_h264 → Zenoh.

Run this on a Mac and watch the published stream on a viewer.
"""
import time
import numpy as np

import adamo

API_KEY = "ak_2M3T7rqPYGubJO2gBsxRoWswKn83z0L6"
WIDTH, HEIGHT, FPS = 1280, 720, 30

robot = adamo.Robot(api_key=API_KEY, name="mac-test")
track = robot.video(
    "synthetic",
    width=WIDTH,
    height=HEIGHT,
    pixel_format="BGRA",
    bitrate_kbps=4000,
    fps=FPS,
)

print(f"Pushing {WIDTH}x{HEIGHT} BGRA @ {FPS}fps via iceoryx2 → vtenc_h264 → Zenoh")
print("Ctrl+C to stop.")

frame = np.zeros((HEIGHT, WIDTH, 4), dtype=np.uint8)
frame[..., 3] = 255  # opaque alpha

xs = np.tile(np.arange(WIDTH, dtype=np.uint8), (HEIGHT, 1))
ys = np.tile(np.arange(HEIGHT, dtype=np.uint8)[:, None], (1, WIDTH))

count = 0
start = time.monotonic()
interval = 1.0 / FPS

try:
    while True:
        t = np.uint8(count & 0xFF)
        frame[..., 0] = xs + t                    # B — uint8 wraps
        frame[..., 1] = ys + np.uint8((count * 2) & 0xFF)  # G
        frame[..., 2] = ((xs.astype(np.uint16) + ys + count * 3) >> 1).astype(np.uint8)  # R

        track.send(frame)

        count += 1
        if count % (FPS * 5) == 0:
            elapsed = time.monotonic() - start
            print(f"[{count:5d} frames] {count/elapsed:5.1f} fps")

        next_t = start + count * interval
        sleep = next_t - time.monotonic()
        if sleep > 0:
            time.sleep(sleep)
except KeyboardInterrupt:
    print("\nStopping.")
