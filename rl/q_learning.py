import numpy as np
import random

class QLearningAgent:
    """
    BUGS FIXED:
    1. actions [10, 30, 50, 80]: max production 80, but mean demand is 52 and
       max demand is 231. Average production (42.5) was below average demand,
       causing inventory to deplete over time. Action space expanded to cover
       the full demand distribution.

    2. Q-table 10x10: too coarse. Upgraded to 20x20 for finer state resolution,
       meaning the agent can learn more nuanced inventory/demand policies.

    3. demand discretization used max_value=300 for both inventory AND demand.
       Demand actual max ~231 — this wasted 20% of Q-table columns (states 8-9
       were never visited). Demand now discretized against its actual range.

    4. epsilon=0.3 (30% random): exploration was insufficient from the start.
       Now starts at 1.0 (full exploration) and decays per episode in the runner.
       Do NOT add epsilon decay inside this class.

    5. alpha=0.1, gamma=0.9: slightly tuned for faster convergence and better
       long-term planning (gamma=0.95 better reflects multi-step supply chains).
    """

    def __init__(self):
        # Expanded action space to cover actual demand distribution
        # Dataset: mean=52, 75th pct=70, 95th pct=107, max=231
        self.actions = [20, 40, 60, 80, 120, 160, 200]  # was [10, 30, 50, 80]

        # Finer state space for richer policy learning
        self.n_bins = 20  # was 10
        self.q_table = np.zeros((self.n_bins, self.n_bins, len(self.actions)))

        self.alpha = 0.2    # was 0.1 — faster convergence
        self.gamma = 0.95   # was 0.9 — better long-term supply chain planning
        self.epsilon = 1.0  # was 0.3 — start with full exploration; decay in runner

    def discretize(self, value, max_value):
        """Map a continuous value to a bin index [0, n_bins-1]."""
        idx = int(value / (max_value / self.n_bins))
        return min(idx, self.n_bins - 1)

    def choose_action(self, inventory, demand):
        i = self.discretize(inventory, max_value=300)
        d = self.discretize(demand, max_value=250)  # was 300; demand max ~231

        if random.random() < self.epsilon:
            return random.randint(0, len(self.actions) - 1)

        return int(np.argmax(self.q_table[i][d]))

    def update(self, inv, dem, action, reward, next_inv, next_dem):
        i  = self.discretize(inv,      max_value=300)
        d  = self.discretize(dem,      max_value=250)
        ni = self.discretize(next_inv, max_value=300)
        nd = self.discretize(next_dem, max_value=250)

        best_next = np.max(self.q_table[ni][nd])

        self.q_table[i][d][action] += self.alpha * (
            reward + self.gamma * best_next - self.q_table[i][d][action]
        ) 