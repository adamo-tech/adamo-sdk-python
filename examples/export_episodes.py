"""Export episodes as numpy arrays for offline processing.

Saves each session as a separate .npz file with aligned joint states.

Usage:
    pip install adamo numpy
    python export_episodes.py <api_key> [output_dir]
"""

import json
import sys
from pathlib import Path

import numpy as np

from adamo.data import connect

API_KEY = sys.argv[1] if len(sys.argv) > 1 else "ak_your_key_here"
OUTPUT_DIR = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("episodes")

client = connect(api_key=API_KEY)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

sessions = client.list_sessions()
print(f"Found {len(sessions)} sessions")

for i, session in enumerate(sessions):
    print(f"\n[{i + 1}/{len(sessions)}] {session.name} ({session.id})")

    timestamps = []
    positions = []

    for record in client.iter_records(session.id, "robot/control/**/joint_states"):
        try:
            data = json.loads(record.payload)
            positions.append(data["positions"])
            timestamps.append(record.timestamp)
        except (json.JSONDecodeError, KeyError):
            continue

    if not timestamps:
        print("  No joint states found, skipping")
        continue

    ts_array = np.array(timestamps, dtype=np.float64)
    pos_array = np.array(positions, dtype=np.float32)

    out_path = OUTPUT_DIR / f"{session.id}.npz"
    np.savez(
        out_path,
        timestamps=ts_array,
        positions=pos_array,
        session_id=session.id,
        session_name=session.name,
    )
    print(f"  Saved {len(timestamps)} steps → {out_path}")

client.close()
print(f"\nDone. Episodes saved to {OUTPUT_DIR}/")
