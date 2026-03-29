"""
FulfillmentAgent — handles the 'Inventory Available?' decision gate in the diagram.

Architecture position:
    Warehouse System → Inventory Available? → FulfillmentAgent → LastMileAgent
                                           → NO → SupplierDiscoveryAgent

CHANGE: Added MAX_HISTORY cap (1000 entries) as a safety net.
The primary fix is in simulation_runner.py which now calls reset() at the start
of each episode. This cap prevents any future regression from causing OOM.
"""

from __future__ import annotations
from typing import List

MAX_HISTORY = 1000  # Safety cap — primary fix is reset() in simulation_runner


class FulfillmentAgent:
    """
    Executes the fulfilment decision once warehouse inventory is known.

    Two-path logic matching the diagram:
        YES path: inventory >= demand → full fulfilment via LastMileAgent
        NO path:  inventory <  demand → partial fulfilment + backorder signal
    """

    SLA_FILL_TARGET = 0.90

    def __init__(self, agent_name: str = "FulfillmentAgent"):
        self.name = agent_name

        # Episode accumulators
        self.total_fulfilled:  float = 0.0
        self.total_demand:     float = 0.0
        self.backorder_total:  float = 0.0
        self.sla_breaches:     int   = 0
        self._step_count:      int   = 0
        self.history:          List[dict] = []

    def fulfill(
        self,
        satisfied:  float,
        demand:     float,
        inventory:  float,
    ) -> float:
        """
        Process fulfilment for one simulation step.

        Args:
            satisfied:  units already dispatched by WarehouseAgent
            demand:     total customer demand this step
            inventory:  remaining warehouse inventory after dispatch

        Returns:
            Confirmed dispatch quantity for LastMileAgent
        """
        self._step_count += 1

        confirmed  = min(satisfied, demand)
        shortfall  = max(0.0, demand - confirmed)
        fill_rate  = confirmed / (demand + 1e-9)

        self.total_fulfilled += confirmed
        self.total_demand    += demand
        self.backorder_total += shortfall
        if fill_rate < self.SLA_FILL_TARGET:
            self.sla_breaches += 1

        # Safety cap: only store recent history to prevent unbounded growth
        if len(self.history) < MAX_HISTORY:
            self.history.append({
                "step":      self._step_count,
                "confirmed": round(confirmed, 1),
                "demand":    round(demand,    1),
                "shortfall": round(shortfall, 1),
                "fill_rate": round(fill_rate, 4),
                "inventory": round(inventory, 1),
            })

        return confirmed

    @property
    def episode_fill_rate(self) -> float:
        if self.total_demand == 0:
            return 1.0
        return round(self.total_fulfilled / self.total_demand, 4)

    @property
    def sla_breach_rate(self) -> float:
        if self._step_count == 0:
            return 0.0
        return round(self.sla_breaches / self._step_count, 4)

    def snapshot(self) -> dict:
        return {
            "episode_fill_rate":  self.episode_fill_rate,
            "total_fulfilled":    round(self.total_fulfilled,  1),
            "total_demand":       round(self.total_demand,     1),
            "backorder_total":    round(self.backorder_total,  1),
            "sla_breaches":       self.sla_breaches,
            "sla_breach_rate":    self.sla_breach_rate,
            "step_count":         self._step_count,
        }

    def reset(self) -> None:
        self.total_fulfilled = 0.0
        self.total_demand    = 0.0
        self.backorder_total = 0.0
        self.sla_breaches    = 0
        self._step_count     = 0
        self.history         = [] 