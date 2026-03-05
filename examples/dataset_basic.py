"""Basic dataset construction — the minimal example.

Usage:
    pip install adamo[ml]
    python dataset_basic.py <api_key>
"""

import sys

from torch.utils.data import DataLoader

from adamo.data import connect

API_KEY = sys.argv[1] if len(sys.argv) > 1 else "ak_your_key_here"

client = connect(api_key=API_KEY)

dataset = client.dataset(
    sessions=client.list_sessions(),
    observation={
        "state": ("robot/control/**/joint_states", "positions"),
    },
    action=("robot/control/**/joint_states", "positions"),
    hz=30,
)

print(f"Dataset: {len(dataset)} samples")
print(f"Stats: {dataset.stats.keys()}")

# Iterate with DataLoader
loader = DataLoader(dataset, batch_size=8, shuffle=True)
batch = next(iter(loader))
print(f"observation.state: {batch['observation.state'].shape}")
print(f"action:            {batch['action'].shape}")

client.close()
