"""Decode and display video frames from a recorded session.

Usage:
    pip install adamo av matplotlib
    python video_frames.py <api_key> [session_id]
"""

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

# Find video topics
video_topics = client.match_topics(SESSION_ID, "robot/video/*")
if not video_topics:
    print("No video topics found")
    client.close()
    sys.exit(1)

topic = video_topics[0]
print(f"Using video topic: {topic}")

# Check video metadata
idx = client.video_index(SESSION_ID, topic)
print(f"  {idx.frame_count} frames, {idx.duration_ms}ms, {idx.avg_fps:.1f} fps")

# Decode and show a grid of frames
frames = []
for frame in client.iter_frames(SESSION_ID, topic, size=(320, 240)):
    frames.append(frame)
    if len(frames) >= 16:
        break

if not frames:
    print("No frames decoded")
    client.close()
    sys.exit(1)

cols = 4
rows = (len(frames) + cols - 1) // cols
fig, axes = plt.subplots(rows, cols, figsize=(12, 3 * rows))
axes = axes.flatten() if rows > 1 else [axes] if cols == 1 else list(axes)

for i, ax in enumerate(axes):
    if i < len(frames):
        ax.imshow(frames[i].image)
        t = frames[i].timestamp - frames[0].timestamp
        ax.set_title(f"t={t:.2f}s")
    ax.axis("off")

fig.suptitle(f"Video Frames — {topic}")
plt.tight_layout()
plt.show()

client.close()
