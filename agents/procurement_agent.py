"""
ProcurementAgent — sits between Production Agent and Supplier in the diagram.

Responsibilities:
    - Validate production orders against available supply
    - Apply safety stock buffer logic
    - Detect disruption-aware procurement strategies
    - Track procurement history for RL feedback
    - Communicate with SupplierDiscoveryAgent when primary supply is constrained

Architecture position (from diagram):
    Production Agent → ProcurementAgent → Logistics Agent
    ProcurementAgent ←→ A2A Communication ←→ Inventory Agent
"""

from __future__ import annotations
from typing import List, Optional


class ProcurementAgent:
    """
    Procurement decision layer between production and fulfilment.

    In the standard flow the RL agent decides production quantity.
    ProcurementAgent validates and adjusts that quantity based on:
        - Available supplier capacity
        - Disruption-aware safety buffers
        - Holding cost constraints

    It is stateless within a step but accumulates episode metrics.
    """

    DISRUPTION_BUFFER_MULTIPLIER = 1.25   # increase order by 25% when disrupted
    MAX_PROCUREMENT_CAP          = 200.0  # hard cap matching RL action space

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

        If disruptions are active the agent proactively buffers the order
        to absorb potential future supply gaps.

        Args:
            required:     RL-agent-requested production quantity
            inventory:    current warehouse inventory
            demand:       current step demand
            disruptions:  list of active disruption type strings
            supplier_cap: maximum the supplier can deliver this step

        Returns:
            Validated procurement quantity (float)
        """
        self._step_count += 1
        active = set(disruptions or [])

        base_qty = required

        # Disruption buffer: order extra when supply is under stress
        if "supplier_failure" in active or "factory_slowdown" in active:
            base_qty = min(
                base_qty * self.DISRUPTION_BUFFER_MULTIPLIER,
                self.MAX_PROCUREMENT_CAP,
            )

        # Demand surge: ensure we can cover the inflated demand
        if "demand_surge" in active:
            surge_cover = demand * 1.1 - inventory
            if surge_cover > base_qty:
                base_qty = min(surge_cover, self.MAX_PROCUREMENT_CAP)

        # Clamp to supplier capacity
        final_qty = min(base_qty, supplier_cap)

        self.total_ordered   += required
        self.total_fulfilled += final_qty
        self.order_history.append({
            "step":       self._step_count,
            "requested":  round(required,   1),
            "approved":   round(final_qty,  1),
            "disrupted":  bool(active),
            "inventory":  round(inventory,  1),
        })

        return final_qty

    def efficiency_rate(self) -> float:
        """Ratio of fulfilled to ordered quantity. 1.0 = perfect."""
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
        """Reset episode state."""
        self.total_ordered   = 0.0
        self.total_fulfilled = 0.0
        self.order_history   = []
        self._step_count     = 0 