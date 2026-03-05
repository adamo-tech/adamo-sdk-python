"""Using dataset stats for input normalization during training.

Shows how to use the auto-computed mean/std for normalizing observations
and actions, which is standard practice in robot learning.

Usage:
    pip install adamo[ml]
    python dataset_normalize.py <api_key>
"""

import sys

import torch
from torch.utils.data import DataLoader

from adamo.data import connect

API_KEY = sys.argv[1] if len(sys.argv) > 1 else "ak_your_key_here"

client = connect(api_key=API_KEY)

dataset = client.dataset(
    sessions=client.list_sessions(name_contains="pick-place"),
    observation={
        "state":   ("robot/control/**/joint_states", "positions"),
        "gripper": ("robot/control/**/joint_states", "gripper"),
    },
    action=("robot/control/**/joint_states", "positions"),
    obs_steps=2,
    action_steps=16,
    hz=30,
)

# Print computed stats
for key, s in dataset.stats.items():
    print(f"{key}:")
    print(f"  mean: {s['mean']}")
    print(f"  std:  {s['std']}")

# Convert stats to tensors for use in training
obs_mean = torch.from_numpy(dataset.stats["observation.state"]["mean"])
obs_std = torch.from_numpy(dataset.stats["observation.state"]["std"])
act_mean = torch.from_numpy(dataset.stats["action"]["mean"])
act_std = torch.from_numpy(dataset.stats["action"]["std"])

# Use in a training loop
loader = DataLoader(dataset, batch_size=32, shuffle=True)

for batch in loader:
    # Normalize observations: (B, obs_steps, D)
    state = (batch["observation.state"] - obs_mean) / (obs_std + 1e-6)

    # Normalize actions: (B, action_steps, D)
    action = (batch["action"] - act_mean) / (act_std + 1e-6)

    print(f"Normalized state range: [{state.min():.2f}, {state.max():.2f}]")
    print(f"Normalized action range: [{action.min():.2f}, {action.max():.2f}]")
    break  # just show one batch

client.close()
