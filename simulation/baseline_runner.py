"""
Heuristic baseline policy — no reinforcement learning.

Represents a human planner using yesterday's demand plus a safety buffer
to set today's production. This is the "doing nothing" benchmark that
answers the stakeholder question: "How much value does the RL add?"

The baseline intentionally uses the same environment and agents as the
RL system so the comparison is fair — the only difference is the
decision-making policy.
"""

from simulation.environment  import SupplyChainEnvironment
from agents.warehouse_agent  import WarehouseAgent
from agents.logistics_agent  import LogisticsAgent
from evaluation.metrics      import compute_metrics


SAFETY_STOCK   = 20
MAX_PRODUCTION = 160   # matches RL agent's max action


def run_baseline_evaluation(predictions: list) -> dict:
    """
    Evaluate a demand-following heuristic policy over the full prediction set.

    Policy rule:
        production_t = min(demand_{t-1} + SAFETY_STOCK, MAX_PRODUCTION)

    This mimics a common real-world practice: look at yesterday's demand,
    add a fixed safety buffer, and place that production order today.
    No learning, no adaptation to disruptions.

    Returns a metrics dict with the same keys as compute_metrics().
    """
    env       = SupplyChainEnvironment()
    warehouse = WarehouseAgent()
    logistics = LogisticsAgent()

    costs          = []
    demands        = []
    satisfied_list = []

    # Warm-start: estimate initial demand from the first 10 observations
    prev_demand = float(sum(predictions[:10]) / max(len(predictions[:10]), 1))

    for day in range(len(predictions) - 1):
        demand     = float(predictions[day])
        production = min(int(prev_demand) + SAFETY_STOCK, MAX_PRODUCTION)
        prev_demand = demand

        shipment  = warehouse.act(env.inventory + production, demand)
        transport = logistics.act(shipment)
        satisfied, cost, delay = env.step(production, transport, demand)

        costs.append(cost)
        demands.append(demand)
        satisfied_list.append(satisfied)

    metrics = compute_metrics(costs, demands, satisfied_list)
    return metrics