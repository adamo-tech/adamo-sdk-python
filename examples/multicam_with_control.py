"""Three cameras from shared memory + a control-data subscription.

This example models a robot with three cameras (front / wrist / rear) whose
frames arrive from external processes via iceoryx2 shared memory, and which
also listens for control data coming in from any participant in the org.

To keep the example self-contained we spin up three synthetic frame
producers (gradients of different hues) in background threads — in a real
deployment these would be separate processes (ROS nodes, camera drivers,
etc.) publishing to the same iceoryx2 service names.

What this shows:
  * :func:`adamo.Robot.attach_video` with ``shm=...`` for multiple cameras
  * A wildcard Zenoh subscription for control messages
  * The Rust pipeline hardware-encoding all three tracks simultaneously
    and publishing them to ``adamo/{org}/{name}/video/{track}``

Run it, then on the same or another machine publish control data::

    import adamo
    s = adamo.connect(api_key="ak_...")
    s.put("ops-console/control/joystick", b'{"axes":[0.5,0.0]}')

and watch it appear in this script's stdout.
"""
from __future__ import annotations

import argparse
import ctypes
import threading
import time

import numpy as np

import adamo


# -- Synthetic camera producers -------------------------------------------------


def _frame_size(width: int, height: int) -> int:
    return width * height * 4  # BGRA


def start_fake_camera(
    service_name: str,
    *,
    width: int,
    height: int,
    hue_offset: int,
    fps: int,
    stop: threading.Event,
) -> threading.Thread:
    """Publish a moving BGRA gradient on an iceoryx2 service.

    Stands in for what a real camera driver would be doing (ROS bridge,
    depthai publisher, gstreamer shmsink, etc.).
    """
    import iceoryx2 as iox2

    def run():
        node = iox2.NodeBuilder.new().create(iox2.ServiceType.Ipc)
        svc = (
            node.service_builder(iox2.ServiceName.new(service_name))
            .publish_subscribe(iox2.Slice[ctypes.c_uint8])
            .enable_safe_overflow(True)
            .subscriber_max_buffer_size(2)
            .open_or_create()
        )
        payload_size = _frame_size(width, height)
        pub = svc.publisher_builder().initial_max_slice_len(payload_size).create()

        xs = np.tile(np.arange(width, dtype=np.uint8), (height, 1))
        ys = np.tile(np.arange(height, dtype=np.uint8)[:, None], (1, width))
        frame = np.zeros((height, width, 4), dtype=np.uint8)
        frame[..., 3] = 255  # alpha

        interval = 1.0 / fps
        start = time.monotonic()
        count = 0
        while not stop.is_set():
            t = np.uint8((count + hue_offset) & 0xFF)
            frame[..., 0] = xs + t                                 # B
            frame[..., 1] = ys + np.uint8((count * 2) & 0xFF)      # G
            frame[..., 2] = ((xs.astype(np.uint16) + ys + count * 3) >> 1).astype(np.uint8)
            data = frame.tobytes()

            sample = pub.loan_slice_uninit(len(data))
            ctypes.memmove(sample.payload_ptr, data, len(data))
            sample.assume_init().send()

            count += 1
            wake = start + count * interval
            sleep = wake - time.monotonic()
            if sleep > 0:
                time.sleep(sleep)

    t = threading.Thread(target=run, name=f"fake-cam-{service_name}", daemon=True)
    t.start()
    return t


# -- Main -----------------------------------------------------------------------


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--api-key", default="ak_2M3T7rqPYGubJO2gBsxRoWswKn83z0L6")
    p.add_argument("--name", default="mac-test")
    p.add_argument("--width", type=int, default=960)
    p.add_argument("--height", type=int, default=540)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--bitrate", type=int, default=3000, help="kbps per track")
    args = p.parse_args()

    cameras = [
        ("front", f"adamo/demo/{args.name}/front",  0),
        ("wrist", f"adamo/demo/{args.name}/wrist", 90),
        ("rear",  f"adamo/demo/{args.name}/rear", 180),
    ]

    # 1) Start the three synthetic camera publishers on iceoryx2
    stop = threading.Event()
    for track_name, shm_service, hue_offset in cameras:
        start_fake_camera(
            shm_service,
            width=args.width, height=args.height,
            hue_offset=hue_offset, fps=args.fps,
            stop=stop,
        )
    time.sleep(0.3)  # let publishers warm up before the SHM subscribers attach

    # 2) Configure the Adamo Robot with three shm-sourced video tracks
    robot = adamo.Robot(api_key=args.api_key, name=args.name)
    for track_name, shm_service, _ in cameras:
        robot.attach_video(
            track_name,
            shm=shm_service,
            width=args.width, height=args.height,
            pixel_format="BGRA",
            bitrate_kbps=args.bitrate, fps=args.fps,
        )
    print(f"attached {len(cameras)} cameras:")
    for track_name, shm_service, _ in cameras:
        print(f"  • {track_name:6s}  ← shm '{shm_service}'")

    # 3) Subscribe to control data from any participant in the org.
    # Using the underlying Zenoh session directly lets us use a wildcard
    # expression spanning all robots. Keys look like:
    #   adamo/{org}/{broadcaster}/control/{channel}
    session = robot.session
    prefix = session._prefix      # "adamo/{org}/"
    pattern = f"{prefix}**/control/**"

    count = 0

    def on_control(sample):
        nonlocal count
        count += 1
        full = str(sample.key_expr)
        # Strip "adamo/{org}/" so the printed key is user-facing
        scoped = full[len(prefix):] if full.startswith(prefix) else full
        payload = bytes(sample.payload)
        preview = payload[:64]
        try:
            text = preview.decode("utf-8")
        except UnicodeDecodeError:
            text = preview.hex()
        print(f"[ctl #{count:04d}] {scoped}  ({len(payload)}B)  {text}")

    sub = session.zenoh.declare_subscriber(pattern, on_control)
    print(f"subscribed to control pattern: {pattern}\n")
    print("Rust pipeline will start on the first SHM frame. Ctrl+C to stop.\n")

    # 4) Run the Rust pipeline (blocks until Ctrl+C)
    try:
        robot.run()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        stop.set()
        sub.undeclare()
        robot.close()


if __name__ == "__main__":
    main()
