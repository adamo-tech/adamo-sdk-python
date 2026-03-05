"""Plot aligned multi-topic data — overlay sensors from different sources.

Usage:
    pip install adamo matplotlib
    python plot_aligned.py <api_key> [session_id]
"""

import json
import sys

import matplotlib.pyplot as plt

from adamo.data import connect

API_KEY = sys.argv[1] if len(sys.argv) > 1 else "ak_your_key_here"
SESSION_ID = sys.argv[2] if len(sys.argv) > 2 else None

client = connect(api_key=API_KEY)

if SESSION_ID is None:
    sessions = client.list_sessions()
    if not sessions:
        print("No sessions found")
        sys.exit(1)
    session = sessions[0]
    SESSION_ID = session.id
    print(f"Using session: {session.name} ({SESSION_ID})")

# Align IMU and joint state data
steps = client.aligned(
    SESSION_ID,
    "robot/sensors/imu",
    "robot/control/**/joint_states",
    window_ms=33,  # ~30 fps alignment
)

if not steps:
    print("No aligned data found. Check that both topics exist in this session.")
    client.close()
    sys.exit(1)

print(f"Got {len(steps)} aligned timesteps")

# Extract aligned values
imu_topic = [k for k in steps[0] if "imu" in k][0]
joint_topic = [k for k in steps[0] if "joint" in k][0]

timestamps = []
ang_vel_x = []
joint_0_pos = []

t0 = next(iter(steps[0].values())).timestamp
for step in steps:
    t = step[imu_topic].timestamp - t0
    timestamps.append(t)

    imu = json.loads(step[imu_topic].payload)
    ang_vel_x.append(imu["angular_velocity"][0])

    joints = json.loads(step[joint_topic].payload)
    joint_0_pos.append(joints["positions"][0])

# Dual-axis plot
fig, ax1 = plt.subplots(figsize=(12, 5))

color1 = "#2196F3"
color2 = "#FF9800"

ax1.plot(timestamps, ang_vel_x, color=color1, linewidth=0.8, label="IMU angular vel X")
ax1.set_xlabel("Time (s)")
ax1.set_ylabel("Angular Velocity (rad/s)", color=color1)
ax1.tick_params(axis="y", labelcolor=color1)

ax2 = ax1.twinx()
ax2.plot(timestamps, joint_0_pos, color=color2, linewidth=0.8, label="Joint 0 position")
ax2.set_ylabel("Joint Position (rad)", color=color2)
ax2.tick_params(axis="y", labelcolor=color2)

fig.suptitle("Aligned IMU + Joint State Data")
fig.legend(loc="upper right", bbox_to_anchor=(0.98, 0.95))
plt.tight_layout()
plt.show()

client.close()
