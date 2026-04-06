"""Shared memory camera source — publishes webcam frames to iceoryx2.

Simulates what a ROS bridge node would do: captures frames from a camera
and writes them into iceoryx2 shared memory for the Adamo SDK to pick up.

Run this in one terminal, then run shm_stream.py in another.

Usage:
    pip install iceoryx2 opencv-python
    python shm_camera_source.py
"""

import ctypes
import struct
import time

import cv2
import iceoryx2 as iox2


SERVICE_NAME = "camera/front"
WIDTH = 1280
HEIGHT = 720
FPS = 30
CAMERA_INDEX = 0

# BGRA: 4 bytes per pixel
FRAME_SIZE = WIDTH * HEIGHT * 4
# 8-byte timestamp header + pixel data
PAYLOAD_SIZE = 8 + FRAME_SIZE


def main():
    cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)

    if not cap.isOpened():
        print(f"Failed to open camera {CAMERA_INDEX}")
        return

    node = iox2.NodeBuilder.new().create(iox2.ServiceType.Ipc)
    svc = (
        node.service_builder(iox2.ServiceName.new(SERVICE_NAME))
        .publish_subscribe(iox2.Slice[ctypes.c_uint8])
        .enable_safe_overflow(True)
        .subscriber_max_buffer_size(2)
        .open_or_create()
    )
    pub = svc.publisher_builder().initial_max_slice_len(PAYLOAD_SIZE).create()

    print(f"Publishing {WIDTH}x{HEIGHT} BGRA @{FPS}fps to iceoryx2 '{SERVICE_NAME}'")
    print("Ctrl+C to stop")

    frame_interval = 1.0 / FPS
    frame_count = 0
    start = time.monotonic()

    try:
        while True:
            loop_start = time.monotonic()

            ret, frame = cap.read()
            if not ret:
                print("Camera read failed")
                break

            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
            pixel_data = frame.tobytes()

            # 8-byte LE timestamp in microseconds + pixel data
            timestamp_us = int(time.time() * 1_000_000)
            payload = struct.pack("<Q", timestamp_us) + pixel_data

            sample = pub.loan_slice_uninit(len(payload))
            ctypes.memmove(sample.payload_ptr, payload, len(payload))
            sample.assume_init().send()

            frame_count += 1

            if frame_count % (FPS * 5) == 0:
                elapsed = time.monotonic() - start
                print(f"[shm-source] {frame_count} frames | {frame_count/elapsed:.1f} fps")

            elapsed = time.monotonic() - loop_start
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        elapsed = time.monotonic() - start
        print(f"Published {frame_count} frames in {elapsed:.1f}s ({frame_count/elapsed:.1f} fps)")


if __name__ == "__main__":
    main()
