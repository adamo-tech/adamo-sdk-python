# Adamo Python SDK

Publish, subscribe, and analyze robot data through Adamo's global infrastructure.

```
pip install adamo
```

## Topics

All data flows through **topics** — slash-separated paths you define per robot. The SDK automatically scopes everything to your organization, so you only need to specify the path starting from the robot name:

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

## Teleoperation

Connect to Adamo and stream data in real time.

```python
import adamo

session = adamo.connect(api_key="ak_...")

# Publish joint states from your robot
session.put("arm-01/control/joint_states", payload)

# Subscribe to a specific robot's sensors
with session.subscribe("arm-01/sensors/**") as sub:
    for sample in sub:
        print(sample.key, len(sample.payload))

# Subscribe to all robots in your org
with session.subscribe("**") as sub:
    for sample in sub:
        print(sample.key)
```

## Video (Shared Memory)

Stream video from any source via shared memory (iceoryx2). Your application writes raw frames into shared memory, and Adamo picks them up for hardware encoding and transport.

```python
from adamo._adamo_video import Robot

robot = Robot(api_key="ak_...")
robot.video(
    name="camera",
    encoder="nvv4l2h264enc",
    source_type="shm",
    shm_service="camera/video",
    v4l2_capture_resolution=[1280, 720],
    source_format="NV12",
    fps=30,
    bitrate=4000,
)
robot.run()  # blocks, streaming video
```

The publisher side uses iceoryx2 directly (Rust, C++, or Python):

```python
import iceoryx2 as iox2
import numpy as np

node = iox2.NodeBuilder().create(iox2.ServiceType.IPC)
service = (
    node.service_builder(iox2.ServiceName.new("camera/video"))
    .publish_subscribe(bytes)
    .open_or_create()
)
publisher = service.publisher_builder().create()

# Publish a frame (raw pixels as bytes)
frame = np.zeros((720, 1280, 3), dtype=np.uint8)  # RGB
sample = publisher.loan_slice_uninit(frame.nbytes)
sample.write_from_fn(lambda i: frame.flat[i])
sample.send()
```

## Data

Download and analyze recorded sessions.

```
pip install adamo[data]
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
pip install adamo[ml]
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
