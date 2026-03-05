"""Download recorded training data from Adamo.

Usage:
    pip install adamo
    python data_download.py <api_key>
"""

import sys

from adamo.data import connect

API_KEY = sys.argv[1] if len(sys.argv) > 1 else "ak_your_key_here"

client = connect(api_key=API_KEY)

# List sessions — filter by date and name
sessions = client.list_sessions(after="2026-03-01", name_contains="pick")
print(f"Found {len(sessions)} sessions")

if not sessions:
    # Fall back to all sessions
    sessions = client.list_sessions()
    print(f"(showing all {len(sessions)} sessions)")

for s in sessions:
    print(f"  {s.id}  {s.name}  ({s.message_count} messages)")

if not sessions:
    client.close()
    sys.exit(0)

session = sessions[0]
print(f"\nUsing session: {session.name} ({session.id})")

# Find topics with wildcards
sensor_topics = client.match_topics(session.id, "robot/sensors/**")
video_topics = client.match_topics(session.id, "robot/video/*")
print(f"Sensor topics: {sensor_topics}")
print(f"Video topics: {video_topics}")

# Stream records with wildcards — no need to list concrete topics
print("\nFirst 10 sensor records:")
for i, r in enumerate(client.iter_records(session.id, "robot/sensors/**")):
    print(f"  [{r.timestamp:.3f}] {r.topic} ({len(r.payload)} bytes)")
    if i >= 9:
        break

# Download video
if video_topics:
    idx = client.video_index(session.id, video_topics[0])
    print(f"\nVideo: {idx.frame_count} frames, {idx.duration_ms}ms, {idx.avg_fps:.1f} fps")
    path = client.download_video(session.id, video_topics[0], "output.mp4")
    print(f"Saved to {path}")

# Aligned multi-modal query
if sensor_topics and video_topics:
    print("\nAligned sensor + video records (first 5 steps):")
    steps = client.aligned(
        session.id,
        "robot/video/*",
        "robot/sensors/**",
        window_ms=50,
    )
    for i, step in enumerate(steps[:5]):
        topics = list(step.keys())
        ts = next(iter(step.values())).timestamp
        print(f"  t={ts:.3f}  topics={topics}")

client.close()
