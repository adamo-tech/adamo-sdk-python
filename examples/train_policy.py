"""Train a visuomotor policy from recorded Adamo sessions.

Usage:
    pip install adamo[ml]
    python train_policy.py <api_key>
"""

import sys

import torch
from torch.utils.data import DataLoader

from adamo.data import connect

API_KEY = sys.argv[1] if len(sys.argv) > 1 else "ak_your_key_here"

BATCH_SIZE = 32
EPOCHS = 50
LR = 1e-4


class SimplePolicy(torch.nn.Module):
    def __init__(self, n_joints: int = 7, action_steps: int = 16):
        super().__init__()
        self.backbone = torch.nn.Sequential(
            torch.nn.Conv2d(3, 32, 3, stride=2, padding=1),
            torch.nn.ReLU(),
            torch.nn.AdaptiveAvgPool2d(1),
            torch.nn.Flatten(),
        )
        self.head = torch.nn.Linear(32, n_joints * action_steps)
        self._n_joints = n_joints
        self._action_steps = action_steps

    def forward(self, img):
        # Use latest observation frame: (B, obs_steps, 3, H, W) → (B, 3, H, W)
        x = img[:, -1]
        return self.head(self.backbone(x)).view(-1, self._action_steps, self._n_joints)


def main():
    client = connect(api_key=API_KEY)

    dataset = client.dataset(
        sessions=client.list_sessions(name_contains="pick-place"),
        observation={
            "images.main":  "robot/video/main",
            "images.wrist": "robot/video/wrist",
            "state":        ("robot/control/**/joint_states", "positions"),
        },
        action=("robot/control/**/joint_states", "positions"),
        obs_steps=2,
        action_steps=16,
        hz=30,
        image_size=(224, 224),
    )

    loader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True)
    model = SimplePolicy()
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    loss_fn = torch.nn.MSELoss()

    for epoch in range(EPOCHS):
        total_loss = 0.0
        for batch in loader:
            pred = model(batch["observation.images.main"])
            loss = loss_fn(pred, batch["action"])
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        avg = total_loss / max(len(loader), 1)
        print(f"Epoch {epoch + 1}/{EPOCHS}  loss={avg:.4f}")

    client.close()


if __name__ == "__main__":
    main()
