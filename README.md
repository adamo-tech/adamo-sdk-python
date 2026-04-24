# Adamo Python SDK

Publish, subscribe, and stream video through Adamo's global Zenoh network.

```
pip install adamo
```

Pre-built wheels cover Linux x86_64, Linux aarch64 (glibc ≥ 2.28, i.e.
Ubuntu 20.04 / RHEL 8 / Debian 11 and newer), and macOS arm64. No source
build is needed on any supported platform.

On Ubuntu 20.04 the system `python3-pip` is 20.0.2, which predates
`manylinux_2_28` tag support — upgrade pip first or our wheels will
look incompatible:

```
python3 -m pip install --upgrade pip
python3 -m pip install adamo
```

The SDK has two faces: a **Zenoh Session** (`adamo.connect`) for data, control,
and messaging, and a **Robot** (`adamo.Robot`) that adds video capture and
hardware encoding.

## Topics

All data flows through **key expressions** — slash-separated paths you define
per robot. The SDK automatically scopes everything to your organisation, so
you only need to specify the path starting from the robot name:

```
{robot_name}/{category}/{stream}
```

For example, a robot called `arm-01` might publish:

| Topic | Description |
|---|---|
| `arm-01/video/main` | Main camera stream |
| `arm-01/video/wrist` | Wrist camera stream |
| `arm-01/control/joint_states` | Joint positions, velocities, efforts |
| `arm-01/sensors/imu` | IMU data |
| `arm-01/sensors/force` | Force/torque sensor |

Use `*` to match one level and `**` to match any depth:

- `arm-01/video/*` — all video streams from arm-01
- `arm-01/**` — everything from arm-01
- `*/video/**` — all video from any robot

## Pub/Sub

```python
import adamo

session = adamo.connect(api_key="ak_...")

# One-shot put
session.put("arm-01/control/joint_states", payload)

# Persistent publisher (higher throughput for repeated puts)
with session.publisher("arm-01/sensors/imu", express=True) as pub:
    pub.put(b"...")

# Subscribe — iterator
with session.subscribe("arm-01/sensors/**") as sub:
    for sample in sub:
        print(sample.key, len(sample.payload))

# Subscribe — callback
sub = session.subscribe("**", callback=lambda s: print(s.key))

# One-shot query
for sample in session.get("arm-01/config/**"):
    print(sample.key, sample.payload)
```

## Liveliness

Discover which robots are online and watch for joins/leaves in real time —
native Zenoh primitive, no polling required.

```python
session = adamo.connect(api_key="ak_...")

# Declare this client as alive
token = session.alive("my-robot")

# Query currently alive participants
print(session.live_tokens())

# Watch for changes
session.on_liveliness(
    callback=lambda key, is_alive: print(f"{'UP' if is_alive else 'DOWN'}: {key}")
)
```

## Video — Rust-driven capture

Use `Robot` when you want Adamo to own the camera. Rust reads from the source,
the hardware encoder produces H.264/H.265/AV1, and Zenoh carries it out.

```python
import adamo

robot = adamo.Robot(api_key="ak_...", name="arm-01")

# V4L2 device capture
robot.attach_video("webcam", device="0", width=1280, height=720, fps=30, bitrate_kbps=4000)

# iceoryx2 shared memory (another process publishes raw frames)
robot.attach_video("front", shm="camera/front", width=1280, height=720, fps=30)

# ROS 2 sensor_msgs/Image topic (rclpy bridge)
robot.attach_video("head", ros="/camera/image_raw", width=1280, height=720, fps=30)

robot.run()  # blocks, streaming video
```

## Video — Python-driven frames

Use `robot.video(...)` when your code owns the frame loop — perception pipelines,
OpenCV, PyTorch overlays, etc. Frames cross into the Rust encoder via iceoryx2
shared memory (zero-copy, same host) and go straight to Zenoh.

```
pip install 'adamo[video]'  # adds iceoryx2 + numpy
```

```python
import cv2
import adamo

robot = adamo.Robot(api_key="ak_...", name="arm-01")
track = robot.video("webcam", width=1280, height=720, pixel_format="BGRA",
                    fps=30, bitrate_kbps=4000)

cap = cv2.VideoCapture(0)
while True:
    ok, frame = cap.read()
    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
    track.send(frame)
```

The Rust pipeline auto-starts on the first frame; if you call
`robot.run()` it blocks instead.

## Control tracks — low-latency, priority-aware

For teleop/control, declare per-track publishers with high priority so they
drain ahead of video under congestion.

```python
robot = adamo.Robot(api_key="ak_...", name="gello-01")
ctl = robot.publish("control/joints", priority=250)  # 0-255, higher = more important

while True:
    ctl.put(encode(read_encoders()))
```

Consume control on a follower robot:

```python
robot = adamo.Robot(api_key="ak_...", name="arm-01")
robot.attach_video("front", device="0")

def on_joints(payload: bytes):
    apply_joints(decode(payload))

robot.subscribe("gello-01", "control/joints", on_joints, priority=250)
robot.run()
```

## Typed control messages

Built-in JSON-encoded message types mirror common ROS messages:

```python
from adamo.operate.control import JointState, Joy, JoystickCommand, decode_control

ctl.put(JointState(names=["j1", "j2"], positions=[0.1, 0.2]).to_json())

for sample in sub:
    msg = decode_control(sample.payload)
    if isinstance(msg, JointState):
        ...
```

## Messaging (send / recv / on_message)

For back-channel messages from viewers (e.g. a web UI) to the robot:

```python
robot = adamo.Robot(api_key="ak_...", name="arm-01")

@robot.on_message
def handle(channel, data):
    if channel == "teleop":
        cmd = json.loads(data)

robot.run()
```

Publishing side:

```python
robot.send("teleop", b'{"action": "stop"}')
```

## Data

Download and analyse recorded sessions.

```
pip install 'adamo[data]'
```

```python
from adamo.data import connect

client = connect(api_key="ak_...")

# List sessions
for s in client.list_sessions():
    print(s.name, s.message_count)

# See what topics a session contains
topics = client.get_topics(s.id)

# Load as DataFrame
df = client.to_dataframe(s.id, "arm-01/sensors/**")

# Download video
client.download_video(s.id, "arm-01/video/main", "video.mp4")
```

## PyTorch Dataset

```
pip install 'adamo[ml]'
```

```python
dataset = client.dataset(
    sessions=client.list_sessions(),
    observation={
        "images": "arm-01/video/main",
        "state": ("arm-01/control/joint_states", "positions"),
    },
    action=("arm-01/control/joint_states", "positions"),
    hz=30,
)
```

## Transport

The SDK connects to the nearest Adamo Zenoh router automatically. The default
is QUIC (reliable streams over a single multiplexed UDP socket); pass
`protocol="udp"` for the lowest-latency unreliable transport or
`protocol="tcp"` for environments that block UDP/QUIC.

```python
adamo.connect(api_key="ak_...")                         # quic
adamo.Robot(api_key="ak_...", name="arm-01", protocol="udp")
```
