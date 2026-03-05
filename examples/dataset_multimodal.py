"""Multi-modal dataset — images + joint states with temporal windowing.

Demonstrates obs_steps/action_steps for diffusion policy or ACT-style training.

Usage:
    pip install adamo[ml]
    python dataset_multimodal.py <api_key>
"""

import sys

from torch.utils.data import DataLoader

from adamo.data import connect

API_KEY = sys.argv[1] if len(sys.argv) > 1 else "ak_your_key_here"

client = connect(api_key=API_KEY)

dataset = client.dataset(
    sessions=client.list_sessions(name_contains="pick-place"),
    observation={
        "images.main":  "robot/video/main",
        "images.wrist": "robot/video/wrist",
        "state":        ("robot/control/**/joint_states", "positions"),
    },
    action=("robot/control/**/joint_states", "positions"),
    obs_steps=2,       # 2 past frames for temporal context
    action_steps=16,   # 16-step action prediction horizon
    hz=30,
    image_size=(224, 224),
)

print(f"Dataset: {len(dataset)} samples")
print(f"Stats keys: {list(dataset.stats.keys())}")

# Check shapes
sample = dataset[0]
for key, val in sample.items():
    print(f"  {key}: {val.shape} {val.dtype}")

# Batch
loader = DataLoader(dataset, batch_size=32, shuffle=True)
batch = next(iter(loader))
print(f"\nBatch shapes:")
for key, val in batch.items():
    print(f"  {key}: {val.shape}")

client.close()
