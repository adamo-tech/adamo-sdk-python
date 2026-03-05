"""Publish sensor data to Adamo."""

import time

import adamo

session = adamo.connect(api_key="ak_your_key_here")

# One-shot put
session.put("my-robot/sensors/temperature", b"22.5")

# Persistent publisher (higher throughput for repeated puts)
with session.publisher("my-robot/sensors/imu", express=True) as pub:
    for i in range(100):
        pub.put(f'{{"x": {i}, "y": 0, "z": 9.8}}'.encode())
        time.sleep(0.01)

session.close()
