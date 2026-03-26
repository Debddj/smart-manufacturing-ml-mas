"""
Deep Q-Network agent for the upscaled multi-warehouse supply chain.

Replaces the tabular QLearningAgent when the state space exceeds what
a Q-table can represent. The current 20×20×7 table (2,800 values) works
fine for 2 state dimensions. With 3 warehouse inventories + demand +
4 disruption flags + supplier state = 10 dimensions, a Q-table would
require 20^10 entries. A DQN handles it with a two-layer MLP and an
experience replay buffer.

Architecture:
    Input(state_dim) → Linear(128) → ReLU → Linear(128) → ReLU → Linear(n_actions)

Training:
    - Experience replay buffer (deque, capacity 50,000)
    - Target network with soft update (τ=0.005)
    - Epsilon-greedy exploration, decayed per episode
    - Huber loss (smooth L1) — more stable than MSE for RL
    - Adam optimiser
    - Double DQN: online selects action, target evaluates it

FIXES APPLIED:
    1. diagnostics() referenced self.device without checking if PyTorch
       is available — caused AttributeError when torch is not installed.
       Fixed with safe getattr fallback.
    2. __import__('numpy') anti-pattern replaced with top-level import.
    3. self.alpha clarified: stores lr for DQN, 0.2 for tabular fallback.
"""

import random
import numpy as np
from collections import deque
from typing import List, Optional

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    import torch.nn.functional as F
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    print("[DQNAgent] WARNING: PyTorch not installed. "
          "Run: pip install torch  "
          "Falling back to tabular Q-learning compatibility mode.")


# ── Constants ─────────────────────────────────────────────────────────────────

MAX_INVENTORY     = 300.0
MAX_DEMAND        = 250.0
BUFFER_CAPACITY   = 50_000
BATCH_SIZE        = 64
TARGET_UPDATE_TAU = 0.005
MIN_REPLAY_SIZE   = 512
TRAIN_EVERY_N     = 4


# ── Network definition ────────────────────────────────────────────────────────

class _QNetwork(nn.Module):
    """Two-hidden-layer MLP Q-function approximator."""

    def __init__(self, state_dim: int, n_actions: int, hidden: int = 128):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, n_actions),
        )

    def forward(self, x):
        return self.net(x)


# ── Replay buffer ─────────────────────────────────────────────────────────────

class _ReplayBuffer:
    """Fixed-size circular buffer for experience replay."""

    def __init__(self, capacity: int):
        self._buf = deque(maxlen=capacity)

    def push(self, state, action, reward, next_state, done):
        self._buf.append((
            np.array(state,      dtype=np.float32),
            int(action),
            float(reward),
            np.array(next_state, dtype=np.float32),
            float(done),
        ))

    def sample(self, batch_size: int):
        batch = random.sample(self._buf, batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)
        return (
            np.array(states,      dtype=np.float32),
            np.array(actions,     dtype=np.int64),
            np.array(rewards,     dtype=np.float32),
            np.array(next_states, dtype=np.float32),
            np.array(dones,       dtype=np.float32),
        )

    def __len__(self):
        return len(self._buf)


# ── Main agent ────────────────────────────────────────────────────────────────

class DQNAgent:
    """
    Deep Q-Network agent for the upscaled supply chain.

    Backward-compatible interface matching QLearningAgent so
    simulation_runner.py requires minimal changes.
    """

    # Class attributes mirroring QLearningAgent for dashboard compatibility
    actions = [20, 40, 60, 80, 120, 160, 200]
    n_bins  = 20

    STATE_DIM = 10

    def __init__(
        self,
        state_dim:   int   = 10,
        hidden_size: int   = 128,
        lr:          float = 1e-3,
        gamma:       float = 0.95,
        epsilon:     float = 1.0,
        device:      str   = None,
    ):
        self.state_dim  = state_dim
        self.n_actions  = len(self.actions)
        self.gamma      = gamma
        self.epsilon    = epsilon

        self._step_count = 0

        if not TORCH_AVAILABLE:
            self._torch  = False
            # Tabular fallback Q-table
            self.q_table = np.zeros((self.n_bins, self.n_bins, self.n_actions))
            self.alpha   = 0.2       # standard Q-learning rate for tabular mode
            return

        self._torch  = True
        self.alpha   = lr            # stored as lr for DQN mode

        self.device = torch.device(
            device if device else ("cuda" if torch.cuda.is_available() else "cpu")
        )

        self._online    = _QNetwork(state_dim, self.n_actions, hidden_size).to(self.device)
        self._target    = _QNetwork(state_dim, self.n_actions, hidden_size).to(self.device)
        self._target.load_state_dict(self._online.state_dict())
        self._target.eval()

        self._optimiser = optim.Adam(self._online.parameters(), lr=lr)
        self._buffer    = _ReplayBuffer(BUFFER_CAPACITY)
        self._losses: List[float] = []

    # ── State construction ─────────────────────────────────────────────────────

    def build_state(
        self,
        inventories:          list,
        demand:               float,
        active_disruptions:   Optional[list] = None,
        supplier_reliability: float = 1.0,
        day:                  int   = 0,
    ) -> np.ndarray:
        """
        Build a normalised state vector from raw environment values.
        Handles both single-warehouse and multi-warehouse configurations.
        """
        active = set(active_disruptions or [])

        invs = list(inventories) + [MAX_INVENTORY] * (3 - len(inventories))
        invs = invs[:3]

        state = [
            invs[0] / MAX_INVENTORY,
            invs[1] / MAX_INVENTORY,
            invs[2] / MAX_INVENTORY,
            min(demand / MAX_DEMAND, 1.0),
            1.0 if "supplier_failure"     in active else 0.0,
            1.0 if "demand_surge"         in active else 0.0,
            1.0 if "logistics_breakdown"  in active else 0.0,
            1.0 if "factory_slowdown"     in active else 0.0,
            float(np.clip(supplier_reliability, 0.0, 1.0)),
            float(np.sin(2 * np.pi * (day % 7) / 7)),
        ]
        return np.array(state, dtype=np.float32)

    # ── Action selection ───────────────────────────────────────────────────────

    def choose_action_full(self, state: np.ndarray) -> int:
        """Select action index from a full state vector (ε-greedy)."""
        if random.random() < self.epsilon:
            return random.randint(0, self.n_actions - 1)

        if not self._torch:
            inv_bin = min(int(state[0] * self.n_bins), self.n_bins - 1)
            dem_bin = min(int(state[3] * self.n_bins), self.n_bins - 1)
            return int(np.argmax(self.q_table[inv_bin][dem_bin]))

        with torch.no_grad():
            t = torch.FloatTensor(state).unsqueeze(0).to(self.device)
            q = self._online(t)
            return int(q.argmax(dim=1).item())

    def choose_action(self, inventory: float, demand: float) -> int:
        """Backward-compatible single-warehouse interface."""
        state = self.build_state(inventories=[inventory], demand=demand)
        return self.choose_action_full(state)

    # ── Experience replay ──────────────────────────────────────────────────────

    def push_experience(
        self,
        state:      np.ndarray,
        action:     int,
        reward:     float,
        next_state: np.ndarray,
        done:       bool = False,
    ):
        """Push a transition into the replay buffer."""
        if not self._torch:
            return
        self._buffer.push(state, action, reward, next_state, done)

    def train_step(self) -> Optional[float]:
        """
        Sample a mini-batch and run one gradient step.
        Returns loss value or None if training did not run.
        """
        if not self._torch:
            return None

        self._step_count += 1
        if (len(self._buffer) < MIN_REPLAY_SIZE
                or self._step_count % TRAIN_EVERY_N != 0):
            return None

        states, actions, rewards, next_states, dones = self._buffer.sample(BATCH_SIZE)

        s  = torch.FloatTensor(states).to(self.device)
        a  = torch.LongTensor(actions).unsqueeze(1).to(self.device)
        r  = torch.FloatTensor(rewards).unsqueeze(1).to(self.device)
        ns = torch.FloatTensor(next_states).to(self.device)
        d  = torch.FloatTensor(dones).unsqueeze(1).to(self.device)

        current_q = self._online(s).gather(1, a)

        # Double DQN: online selects action, target evaluates it
        with torch.no_grad():
            best_actions = self._online(ns).argmax(dim=1, keepdim=True)
            target_q     = r + self.gamma * (1 - d) * self._target(ns).gather(1, best_actions)

        loss = F.smooth_l1_loss(current_q, target_q)

        self._optimiser.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self._online.parameters(), max_norm=10.0)
        self._optimiser.step()
        self._soft_update_target()

        loss_val = loss.item()
        self._losses.append(loss_val)
        return loss_val

    def _soft_update_target(self):
        for target_p, online_p in zip(
            self._target.parameters(), self._online.parameters()
        ):
            target_p.data.copy_(
                TARGET_UPDATE_TAU * online_p.data
                + (1 - TARGET_UPDATE_TAU) * target_p.data
            )

    # ── Backward-compatible tabular update ────────────────────────────────────

    def update(
        self,
        inv:      float,
        dem:      float,
        action:   int,
        reward:   float,
        next_inv: float,
        next_dem: float,
    ):
        """
        Backward-compatible interface matching QLearningAgent.update().
        Builds state vectors and delegates to push_experience + train_step.
        """
        state      = self.build_state([inv],      dem)
        next_state = self.build_state([next_inv], next_dem)
        self.push_experience(state, action, reward, next_state, done=False)
        self.train_step()

        # Maintain tabular fallback for dashboard compatibility
        if not self._torch:
            i  = min(int(inv      / (300.0 / self.n_bins)), self.n_bins - 1)
            d  = min(int(dem      / (250.0 / self.n_bins)), self.n_bins - 1)
            ni = min(int(next_inv / (300.0 / self.n_bins)), self.n_bins - 1)
            nd = min(int(next_dem / (250.0 / self.n_bins)), self.n_bins - 1)
            best_next = np.max(self.q_table[ni][nd])
            self.q_table[i][d][action] += self.alpha * (
                reward + self.gamma * best_next - self.q_table[i][d][action]
            )

    # ── Persistence ────────────────────────────────────────────────────────────

    def save(self, path: str = "outputs/dqn_weights.pt"):
        """Save online network weights to disk."""
        if not self._torch:
            return
        import os
        os.makedirs(os.path.dirname(path), exist_ok=True)
        torch.save({
            "online":  self._online.state_dict(),
            "target":  self._target.state_dict(),
            "epsilon": self.epsilon,
            "steps":   self._step_count,
        }, path)
        print(f"  DQN weights saved → {path}")

    def load(self, path: str = "outputs/dqn_weights.pt"):
        """Load previously saved weights."""
        if not self._torch:
            return
        checkpoint = torch.load(path, map_location=self.device)
        self._online.load_state_dict(checkpoint["online"])
        self._target.load_state_dict(checkpoint["target"])
        self.epsilon     = checkpoint.get("epsilon", 0.01)
        self._step_count = checkpoint.get("steps",   0)
        print(f"  DQN weights loaded ← {path}")

    # ── Diagnostics ────────────────────────────────────────────────────────────

    def diagnostics(self) -> dict:
        """
        Return training health indicators.

        FIX: original code accessed self.device unconditionally — caused
        AttributeError when PyTorch is not installed. Now uses safe getattr.
        """
        recent_losses = self._losses[-200:] if self._torch else []
        # FIX: getattr with fallback prevents AttributeError when _torch=False
        device_str = str(getattr(self, "device", "cpu"))
        return {
            "epsilon":         round(self.epsilon, 4),
            "buffer_size":     len(self._buffer) if self._torch else 0,
            "steps_trained":   self._step_count,
            "avg_loss_recent": round(float(np.mean(recent_losses)), 6) if recent_losses else None,
            "backend":         "pytorch" if self._torch else "tabular_fallback",
            "device":          device_str,
        }