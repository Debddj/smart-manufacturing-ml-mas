"""
Multi-objective reward function for the upscaled DQN supply chain agent.

Extends the original tiered reward with:
    - Branch penalty: Branch C (external sourcing) costs more than A or B
    - Transfer penalty: inter-warehouse transfers consume logistics capacity
    - Supplier diversity bonus: using multiple supplier nodes is more resilient
    - Per-warehouse balance incentive: prevent one node draining while others overflow

The weights are exposed as keyword arguments so simulation_runner.py can
tune them without editing this file. Default weights reproduce behaviour
close to the original system for backward compatibility.

Usage (drop-in replacement for original compute_reward):
    reward = compute_reward(satisfied, demand, cost, production=80)

Usage (full multi-objective with branch info):
    reward = compute_reward_multi(
        satisfied=490, demand=500, cost=312.0,
        production=80, branch="B", transfer_units=20,
        supplier_diversity=0.7,
        inventory_balance_score=0.85,
    )
"""

import numpy as np


# ── Original reward (unchanged — backward compatible) ─────────────────────────

def compute_reward(satisfied: float, demand: float, cost: float,
                   production: float = 0) -> float:
    """
    Original reward function.
    Kept intact for backward compatibility with existing simulation_runner.py.
    """
    service_level = satisfied / (demand + 1e-5)

    reward = (
        service_level * 20
        - cost * 0.005
    )

    if service_level >= 0.90:
        reward += 5.0
    if service_level >= 0.95:
        reward += 3.0

    safety_stock     = 20
    excess_production = max(0, production - (demand + safety_stock))
    reward -= excess_production * 0.05

    return reward


# ── Multi-objective reward for DQN + multi-warehouse ──────────────────────────

# Branch penalties: C is expensive (external sourcing costs), B has transfer overhead
BRANCH_PENALTIES = {
    "A": 0.0,    # ideal — local fulfilment, no extra cost
    "B": 0.5,    # inter-warehouse transfer takes time and logistics capacity
    "C": 3.0,    # external sourcing — supplier lead time, no control over quality
}

def compute_reward_multi(
    satisfied:             float,
    demand:                float,
    cost:                  float,
    production:            float = 0,
    branch:                str   = "A",
    transfer_units:        float = 0.0,
    supplier_diversity:    float = 1.0,   # 0–1: fraction of active supplier nodes used
    inventory_balance_score: float = 1.0, # 0–1: how evenly distributed inventory is
    # Weight knobs — tune these to shift agent behaviour
    w_service:    float = 20.0,
    w_cost:       float = 0.005,
    w_sla_bonus:  float = 5.0,
    w_stretch:    float = 3.0,
    w_overstock:  float = 0.05,
    w_branch:     float = 1.0,
    w_transfer:   float = 0.02,
    w_diversity:  float = 1.0,
    w_balance:    float = 0.5,
) -> float:
    """
    Multi-objective reward for the upscaled DQN agent.

    Dimensions:
        1. Service level    — primary objective (fill rate × weight)
        2. Cost efficiency  — penalise total operational cost
        3. SLA bonuses      — crossing 0.90 and 0.95 thresholds
        4. Over-production  — penalise stocking excess beyond safety buffer
        5. Branch penalty   — discourage expensive fulfilment paths
        6. Transfer penalty — each transferred unit has a logistics cost
        7. Supplier diversity — reward using multiple supplier nodes
        8. Inventory balance  — reward evenly distributed stock

    Returns:
        float reward value (typically in range -20 to +35 per step)
    """
    service_level = satisfied / (demand + 1e-5)

    # Core service + cost terms
    reward = (
        service_level * w_service
        - cost * w_cost
    )

    # SLA bonus structure (tiered — no reward for over-stocking beyond 0.97)
    if service_level >= 0.90:
        reward += w_sla_bonus
    if service_level >= 0.95:
        reward += w_stretch

    # Over-production penalty
    safety_stock      = 20
    excess_production = max(0, production - (demand + safety_stock))
    reward           -= excess_production * w_overstock

    # Branch penalty: incentivise A over B over C
    reward -= BRANCH_PENALTIES.get(branch, 0.0) * w_branch

    # Transfer penalty: logistics bandwidth is finite
    reward -= transfer_units * w_transfer

    # Supplier diversity bonus: using multiple nodes is more resilient
    # supplier_diversity = 0 means always using one node (fragile)
    # supplier_diversity = 1 means using all available nodes (robust)
    reward += (supplier_diversity - 0.5) * w_diversity

    # Inventory balance bonus: uniform distribution across warehouses is better
    # inventory_balance_score = 1.0 means perfectly balanced, 0.0 means all in one node
    reward += (inventory_balance_score - 0.5) * w_balance

    return reward


def compute_inventory_balance_score(inventories: list[float]) -> float:
    """
    Score how evenly inventory is distributed across warehouse nodes.
    Returns 1.0 for perfect balance, 0.0 for all stock in one node.

    Used as input to compute_reward_multi's inventory_balance_score param.
    """
    total = sum(inventories)
    if total == 0:
        return 1.0   # all empty — balanced (and crisis handled elsewhere)
    n        = len(inventories)
    ideal    = total / n
    deviations = [abs(inv - ideal) / (total + 1e-9) for inv in inventories]
    imbalance  = sum(deviations) / n
    return float(np.clip(1.0 - imbalance * n, 0.0, 1.0))


def reward_weight_profile(profile: str = "balanced") -> dict:
    """
    Return a preset weight dict for common operational priorities.
    Pass the returned dict as **kwargs to compute_reward_multi.

    Profiles:
        "balanced"   — default, equal weight on service and cost
        "speed"      — prioritise fill rate, accept higher cost
        "cost"       — aggressive cost reduction, accept slight service drop
        "resilience" — penalise Branch C heavily, reward supplier diversity
    """
    profiles = {
        "balanced": {
            "w_service": 20.0, "w_cost": 0.005, "w_sla_bonus": 5.0,
            "w_stretch": 3.0, "w_overstock": 0.05, "w_branch": 1.0,
            "w_transfer": 0.02, "w_diversity": 1.0, "w_balance": 0.5,
        },
        "speed": {
            "w_service": 30.0, "w_cost": 0.002, "w_sla_bonus": 8.0,
            "w_stretch": 5.0, "w_overstock": 0.01, "w_branch": 0.5,
            "w_transfer": 0.01, "w_diversity": 0.5, "w_balance": 0.2,
        },
        "cost": {
            "w_service": 15.0, "w_cost": 0.010, "w_sla_bonus": 4.0,
            "w_stretch": 2.0, "w_overstock": 0.10, "w_branch": 2.0,
            "w_transfer": 0.05, "w_diversity": 0.5, "w_balance": 0.3,
        },
        "resilience": {
            "w_service": 20.0, "w_cost": 0.004, "w_sla_bonus": 5.0,
            "w_stretch": 3.0, "w_overstock": 0.03, "w_branch": 3.0,
            "w_transfer": 0.01, "w_diversity": 2.0, "w_balance": 1.0,
        },
    }
    return profiles.get(profile, profiles["balanced"])