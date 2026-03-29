"""
ProcurementAgent — sits between Production Agent and Supplier in the diagram.

CHANGE: Added MAX_HISTORY cap (1000 entries) as a safety net.
The primary fix is in simulation_runner.py which now calls reset() at the start
of each episode. This cap prevents any future regression from causing OOM.
"""

from __future__ import annotations
from typing import List, Optional

MAX_HISTORY = 1000  # Safety cap — primary fix is reset() in simulation_runner


class ProcurementAgent:
    """
    Procurement decision layer between production and fulfilment.

    In the standard flow the RL agent decides production quantity.
    ProcurementAgent validates and adjusts that quantity based on:
        - Available supplier capacity
        - Disruption-aware safety buffers
        - Holding cost constraints
    """

    DISRUPTION_BUFFER_MULTIPLIER = 1.25
    MAX_PROCUREMENT_CAP          = 200.0

    def __init__(self, agent_name: str = "ProcurementAgent"):
        self.name = agent_name

        # Episode tracking
        self.total_ordered:   float = 0.0
        self.total_fulfilled: float = 0.0
        self.order_history:   List[dict] = []
        self._step_count:     int   = 0

    def process_order(
        self,
        required:     float,
        inventory:    float,
        demand:       float,
        disruptions:  Optional[list] = None,
        supplier_cap: float = 180.0,
    ) -> float:
        """
        Process a production order and return the validated procurement quantity.
        """
        self._step_count += 1
        active = set(disruptions or [])

        base_qty = required

        if "supplier_failure" in active or "factory_slowdown" in active:
            base_qty = min(
                base_qty * self.DISRUPTION_BUFFER_MULTIPLIER,
                self.MAX_PROCUREMENT_CAP,
            )

        if "demand_surge" in active:
            surge_cover = demand * 1.1 - inventory
            if surge_cover > base_qty:
                base_qty = min(surge_cover, self.MAX_PROCUREMENT_CAP)

        final_qty = min(base_qty, supplier_cap)

        self.total_ordered   += required
        self.total_fulfilled += final_qty

        # Safety cap: only store recent history to prevent unbounded growth
        if len(self.order_history) < MAX_HISTORY:
            self.order_history.append({
                "step":       self._step_count,
                "requested":  round(required,   1),
                "approved":   round(final_qty,  1),
                "disrupted":  bool(active),
                "inventory":  round(inventory,  1),
            })

        return final_qty

    def efficiency_rate(self) -> float:
        if self.total_ordered == 0:
            return 1.0
        return round(self.total_fulfilled / self.total_ordered, 4)

    def snapshot(self) -> dict:
        return {
            "total_ordered":   round(self.total_ordered,   1),
            "total_fulfilled": round(self.total_fulfilled, 1),
            "efficiency_rate": self.efficiency_rate(),
            "order_count":     self._step_count,
        }

    def reset(self) -> None:
        self.total_ordered   = 0.0
        self.total_fulfilled = 0.0
        self.order_history   = []
        self._step_count     = 0  