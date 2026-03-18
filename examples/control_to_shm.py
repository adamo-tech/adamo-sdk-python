"""Bridge: subscribe to WebXR controller data from Zenoh and republish to iceoryx2.

The WebXR app publishes VR controller tracking as CDR-encoded ROS messages:

    adamo/{org}/{robot}/control/cdr/xr_tracking
    ├── /head_pose              → geometry_msgs/msg/PoseStamped
    ├── /controller/left        → geometry_msgs/msg/PoseStamped
    ├── /controller/left/joy    → sensor_msgs/msg/Joy
    ├── /controller/right       → geometry_msgs/msg/PoseStamped
    └── /controller/right/joy   → sensor_msgs/msg/Joy

This script decodes the CDR envelope, extracts the subtopic and payload,
and republishes each message to a per-subtopic iceoryx2 service so your
robot control stack can read them from shared memory.

Usage:
    pip install adamo iceoryx2
    python control_to_shm.py

Flow:
    VR headset (WebXR controllers)
        → Zenoh (adamo cloud)
        → this script
        → iceoryx2 shared memory (one service per subtopic)
        → robot control stack
"""

import ctypes
import json
import signal
import struct
import time

import adamo
import iceoryx2 as iox2

# -- Config ------------------------------------------------------------------

API_KEY = "ak_2M3T7rqPYGubJO2gBsxRoWswKn83z0L6"
ROBOT_NAME = "shm-test"

# Zenoh topic pattern — subscribes to all control data for this robot
CONTROL_TOPIC = f"{ROBOT_NAME}/control/**"

# iceoryx2 service name prefix. Subtopics become separate services:
#   xr/head_pose, xr/controller/left, xr/controller/left/joy, etc.
SHM_PREFIX = "xr"

# -- CDR envelope decoder ----------------------------------------------------


def decode_cdr_envelope(data: bytes) -> tuple[str, str, bytes] | None:
    """Decode CDR-wrapped ROS message.

    Wire format: [u32be topic_len][topic_utf8][u32be type_len][type_utf8][cdr_payload]

    Returns (topic, type_name, cdr_payload) or None if not CDR-encoded.
    """
    if len(data) < 8:
        return None
    try:
        offset = 0
        topic_len = struct.unpack(">I", data[offset : offset + 4])[0]
        offset += 4
        if offset + topic_len > len(data):
            return None
        topic = data[offset : offset + topic_len].decode("utf-8")
        offset += topic_len

        type_len = struct.unpack(">I", data[offset : offset + 4])[0]
        offset += 4
        if offset + type_len > len(data):
            return None
        type_name = data[offset : offset + type_len].decode("utf-8")
        offset += type_len

        cdr_payload = data[offset:]
        return (topic, type_name, cdr_payload)
    except Exception:
        return None


def _skip_cdr_header(cdr: bytes) -> int:
    """Skip CDR header (4 bytes) + ROS Header (stamp + frame_id), return offset.

    ROS Header layout in CDR (little-endian):
      [4] CDR header (00 01 00 00)
      [4] stamp.sec (u32)
      [4] stamp.nanosec (u32)
      [4] frame_id length (u32, includes null terminator)
      [N] frame_id bytes + null
      [P] padding to 4-byte alignment
    """
    off = 4  # CDR header
    off += 8  # stamp (sec + nanosec)
    fid_len = struct.unpack_from("<I", cdr, off)[0]
    off += 4 + fid_len
    # Align to 4 bytes
    off = (off + 3) & ~3
    return off


def decode_pose_stamped(cdr: bytes) -> dict | None:
    """Decode geometry_msgs/msg/PoseStamped from CDR (little-endian).

    Returns dict with position [x,y,z] and quaternion [x,y,z,w] (ROS order).
    """
    try:
        off = _skip_cdr_header(cdr)
        # 7 doubles: px, py, pz, qx, qy, qz, qw (56 bytes)
        if off + 56 > len(cdr):
            return None
        values = struct.unpack_from("<7d", cdr, off)
        return {
            "position": list(values[0:3]),
            "quaternion": list(values[3:7]),  # [x, y, z, w]
        }
    except Exception:
        return None


def decode_joy(cdr: bytes) -> dict | None:
    """Decode sensor_msgs/msg/Joy from CDR (little-endian).

    Returns dict with axes (list[float]) and buttons (list[int]).
    """
    try:
        off = _skip_cdr_header(cdr)
        # axes: u32 count + float32[]
        n_axes = struct.unpack_from("<I", cdr, off)[0]
        off += 4
        if n_axes > 100:
            return None  # sanity check
        axes = list(struct.unpack_from(f"<{n_axes}f", cdr, off))
        off += n_axes * 4
        # buttons: u32 count + int32[]
        n_buttons = struct.unpack_from("<I", cdr, off)[0]
        off += 4
        if n_buttons > 100:
            return None
        buttons = list(struct.unpack_from(f"<{n_buttons}i", cdr, off))
        return {"axes": axes, "buttons": buttons}
    except Exception:
        return None


# -- Setup -------------------------------------------------------------------

running = True


def on_sigint(_sig, _frame):
    global running
    running = False
    print("\nShutting down...")


signal.signal(signal.SIGINT, on_sigint)

# Connect to Adamo (Zenoh)
session = adamo.connect(api_key=API_KEY)
print(f"Connected to Adamo | subscribing to: {CONTROL_TOPIC}")

# iceoryx2 node + publisher cache (one per subtopic)
node = iox2.NodeBuilder.new().create(iox2.ServiceType.Ipc)
publishers: dict[str, object] = {}


def get_publisher(subtopic: str):
    """Get or create an iceoryx2 publisher for the given subtopic."""
    if subtopic not in publishers:
        service_name = f"{SHM_PREFIX}{subtopic}"
        service = (
            node.service_builder(iox2.ServiceName.new(service_name))
            .publish_subscribe(iox2.Slice[ctypes.c_uint8])
            .open_or_create()
        )
        pub = (
            service.publisher_builder()
            .initial_max_slice_len(512)
            .allocation_strategy(iox2.AllocationStrategy.PowerOfTwo)
            .create()
        )
        publishers[subtopic] = pub
        print(f"  Created SHM publisher: {service_name}")
    return publishers[subtopic]


def publish_to_shm(subtopic: str, data: bytes):
    """Publish raw bytes to the iceoryx2 service for this subtopic."""
    pub = get_publisher(subtopic)
    sample = pub.loan_slice_uninit(len(data))
    payload = sample.payload()
    for i in range(len(data)):
        payload[i] = data[i]
    sample = sample.assume_init()
    sample.send()


# -- Bridge loop -------------------------------------------------------------

count = 0
print("Listening for XR controller data...")

with session.subscribe(CONTROL_TOPIC) as sub:
    while running:
        sample = sub.try_recv()
        if sample is None:
            time.sleep(0.001)
            continue

        data = sample.payload

        # Try CDR envelope decode (WebXR tracking messages)
        envelope = decode_cdr_envelope(data)
        if envelope is not None:
            topic, type_name, cdr_payload = envelope

            # Decode and republish as JSON to shared memory
            if "PoseStamped" in type_name:
                pose = decode_pose_stamped(cdr_payload)
                if pose:
                    publish_to_shm(topic, json.dumps(pose).encode())
            elif "Joy" in type_name:
                joy = decode_joy(cdr_payload)
                if joy:
                    publish_to_shm(topic, json.dumps(joy).encode())
            else:
                # Unknown type — forward raw CDR
                publish_to_shm(topic, cdr_payload)
        else:
            # Not CDR — forward raw payload (e.g. JSON control messages)
            subtopic = sample.key.rsplit("/", 1)[-1] if "/" in sample.key else "raw"
            publish_to_shm(f"/{subtopic}", data)

        count += 1
        if count % 100 == 0:
            print(f"Forwarded {count} messages | topics: {list(publishers.keys())}")

session.close()
print(f"Done. Forwarded {count} total messages.")
