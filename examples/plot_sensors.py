"""Plot sensor data from a recorded session.

Usage:
    pip install adamo matplotlib
    python plot_sensors.py <api_key> [session_id]
"""

import json
import sys

import matplotlib.pyplot as plt

from adamo.data import connect

API_KEY = sys.argv[1] if len(sys.argv) > 1 else "ak_your_key_here"
SESSION_ID = sys.argv[2] if len(sys.argv) > 2 else None

client = connect(api_key=API_KEY)

# Pick a session
if SESSION_ID is None:
    sessions = client.list_sessions()
    if not sessions:
        print("No sessions found")
        sys.exit(1)
    session = sessions[0]
    SESSION_ID = session.id
    print(f"Using session: {session.name} ({SESSION_ID})")

# Stream joint state records
timestamps = []
positions = []

for record in client.iter_records(SESSION_ID, "robot/control/**/joint_states"):
    data = json.loads(record.payload)
    timestamps.append(record.timestamp)
    positions.append(data["positions"])

if not timestamps:
    print("No joint state records found")
    client.close()
    sys.exit(1)

# Normalize timestamps to start at 0
t0 = timestamps[0]
times = [t - t0 for t in timestamps]

# Plot each joint
n_joints = len(positions[0])
fig, axes = plt.subplots(n_joints, 1, figsize=(12, 2 * n_joints), sharex=True)
if n_joints == 1:
    axes = [axes]

for j in range(n_joints):
    vals = [p[j] for p in positions]
    axes[j].plot(times, vals, linewidth=0.8)
    axes[j].set_ylabel(f"Joint {j}")
    axes[j].grid(True, alpha=0.3)

axes[-1].set_xlabel("Time (s)")
fig.suptitle("Joint Positions Over Time")
plt.tight_layout()
plt.show()

client.close()
