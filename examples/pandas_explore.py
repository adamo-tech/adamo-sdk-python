"""Explore session data with pandas DataFrames.

Usage:
    pip install adamo[data]
    python pandas_explore.py <api_key> [session_id]
"""

import json
import sys

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

# Load all sensor data into a DataFrame
df = client.to_dataframe(SESSION_ID, "robot/sensors/**", "robot/control/**")
print(f"\nDataFrame: {len(df)} rows")
print(f"Columns: {list(df.columns)}")
print(f"\nTopics:\n{df['topic'].value_counts().to_string()}")

# Parse JSON payloads for a specific topic
joint_df = df[df["topic"].str.contains("joint_states")].copy()
if not joint_df.empty:
    joint_df["parsed"] = joint_df["payload"].apply(lambda b: json.loads(b))
    joint_df["n_joints"] = joint_df["parsed"].apply(lambda d: len(d.get("positions", [])))
    print(f"\nJoint state records: {len(joint_df)}")
    print(f"Joints per record: {joint_df['n_joints'].iloc[0]}")

    # Time range
    t_start = joint_df["timestamp"].min()
    t_end = joint_df["timestamp"].max()
    print(f"Duration: {t_end - t_start:.1f}s")
    print(f"Avg frequency: {len(joint_df) / (t_end - t_start):.1f} Hz")

client.close()
