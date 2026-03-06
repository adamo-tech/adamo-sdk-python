# Adamo Python SDK

Publish, subscribe, and analyze robot data through Adamo's global infrastructure.

```
pip install adamo
```

## Teleoperation

Connect to Adamo and stream data in real time.

```python
import adamo

session = adamo.connect(api_key="ak_...")

# Publish
session.put("robot/sensors/imu", payload)

# Subscribe
with session.subscribe("robot/sensors/**") as sub:
    for sample in sub:
        print(sample.key, len(sample.payload))
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

# Load as DataFrame
df = client.to_dataframe(s.id, "robot/sensors/**")

# Download video
client.download_video(s.id, "robot/video/main", "video.mp4")
```

## PyTorch Dataset

```
pip install adamo[ml]
```

```python
dataset = client.dataset(
    sessions=client.list_sessions(),
    observation={"images": "robot/video/main", "state": ("robot/control/joint_states", "positions")},
    action=("robot/control/joint_states", "positions"),
    hz=30,
)
```
