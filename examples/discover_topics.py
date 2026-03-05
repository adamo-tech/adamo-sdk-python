"""Discover what topics are in your recorded sessions.

Run this first to understand what data is available before building
a dataset or writing a training script.

Usage:
    pip install adamo
    python discover_topics.py <api_key>
"""

import json
import sys

from adamo.data import connect

API_KEY = sys.argv[1] if len(sys.argv) > 1 else "ak_your_key_here"

client = connect(api_key=API_KEY)

# ── List all sessions ────────────────────────────────────────────────────

sessions = client.list_sessions()
print(f"Found {len(sessions)} sessions\n")

for s in sessions:
    print(f"  {s.name:<30}  {s.id}  ({s.message_count} messages)")

if not sessions:
    client.close()
    sys.exit(0)

# ── Pick a session and list its topics ───────────────────────────────────

session = sessions[0]
print(f"\n{'=' * 60}")
print(f"Session: {session.name}")
print(f"ID:      {session.id}")
print(f"{'=' * 60}\n")

topics = client.get_topics(session.id)
print(f"Topics ({len(topics)}):")
for t in topics:
    print(f"  {t}")

# ── Categorize topics ───────────────────────────────────────────────────

video_topics = [t for t in topics if "/video/" in t]
control_topics = [t for t in topics if "/control/" in t]
sensor_topics = [t for t in topics if "/sensors/" in t]
stats_topics = [t for t in topics if "/stats/" in t]
other_topics = [t for t in topics if t not in video_topics + control_topics + sensor_topics + stats_topics]

print(f"\nVideo topics:   {video_topics or '(none)'}")
print(f"Control topics: {control_topics or '(none)'}")
print(f"Sensor topics:  {sensor_topics or '(none)'}")
print(f"Stats topics:   {stats_topics or '(none)'}")
if other_topics:
    print(f"Other topics:   {other_topics}")

# ── Inspect video topics ────────────────────────────────────────────────

if video_topics:
    print(f"\n--- Video Details ---")
    for t in video_topics:
        idx = client.video_index(session.id, t)
        print(f"  {t}")
        print(f"    {idx.frame_count} frames, {idx.avg_fps:.0f} fps, {idx.duration_ms / 1000:.1f}s")

# ── Peek at control/sensor payloads ─────────────────────────────────────

for label, topic_list in [("Control", control_topics), ("Sensor", sensor_topics)]:
    if not topic_list:
        continue
    print(f"\n--- {label} Payload Examples ---")
    for t in topic_list:
        records = list(client.iter_records(session.id, t))
        if not records:
            continue
        try:
            data = json.loads(records[0].payload)
            fields = list(data.keys())
            print(f"  {t}")
            print(f"    Fields: {fields}")
            # Show shape of array fields
            for k, v in data.items():
                if isinstance(v, list):
                    print(f"    {k}: list[{len(v)}]  e.g. {v[:3]}{'...' if len(v) > 3 else ''}")
                elif isinstance(v, (int, float)):
                    print(f"    {k}: {type(v).__name__}  = {v}")
        except (json.JSONDecodeError, TypeError):
            print(f"  {t}: binary payload ({len(records[0].payload)} bytes)")

# ── Show what you'd pass to client.dataset() ────────────────────────────

print(f"\n--- Suggested dataset() call ---")
print("dataset = client.dataset(")
print(f'    sessions=client.list_sessions(name_contains="{session.name[:15]}"),')
print("    observation={")
for t in video_topics:
    track_name = t.rsplit("/", 1)[-1]
    print(f'        "images.{track_name}": "{t}",')
for t in control_topics:
    records = list(client.iter_records(session.id, t))
    if records:
        try:
            data = json.loads(records[0].payload)
            for field, val in data.items():
                if isinstance(val, list) and all(isinstance(x, (int, float)) for x in val):
                    print(f'        "state": ("{t}", "{field}"),')
                    break
        except (json.JSONDecodeError, TypeError):
            pass
print("    },")
# Suggest action from control topic
for t in control_topics:
    records = list(client.iter_records(session.id, t))
    if records:
        try:
            data = json.loads(records[0].payload)
            for field, val in data.items():
                if isinstance(val, list) and all(isinstance(x, (int, float)) for x in val):
                    print(f'    action=("{t}", "{field}"),')
                    break
        except (json.JSONDecodeError, TypeError):
            pass
    break
print("    obs_steps=2,")
print("    action_steps=16,")
print("    hz=30,")
if video_topics:
    print("    image_size=(224, 224),")
print(")")

client.close()
