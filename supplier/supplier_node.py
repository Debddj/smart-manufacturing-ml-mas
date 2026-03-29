"""
SupplierNode — a single node in the decentralised supplier network.

Architecture position (from diagram):
    SupplierDiscoveryAgent → Supplier Node Network → Smart Contract Agreement

Each node maintains its own inventory, reliability, and contract state.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SupplierNode:
    """
    A single supplier in the decentralised network.

    Attributes:
        node_id:        unique identifier e.g. "SUP-001"
        name:           human-readable supplier name
        capacity:       max units deliverable per step
        inventory:      current available stock
        reliability:    probability of successful fulfilment (0–1)
        cost_per_unit:  unit cost for this supplier
        lead_time:      steps before delivery arrives
        region:         geographic region (local / regional / remote)
        active:         whether this supplier is currently operational
    """
    node_id:       str
    name:          str
    capacity:      float = 100.0
    inventory:     float = 200.0
    reliability:   float = 0.90
    cost_per_unit: float = 1.5
    lead_time:     int   = 1
    region:        str   = "regional"
    active:        bool  = True

    # State fields (not in __init__ signature)
    _contracts:       list = field(default_factory=list, repr=False, init=False)
    _total_supplied:  float = field(default=0.0,          repr=False, init=False)
    _disrupted_steps: int   = field(default=0,            repr=False, init=False)

    def supply(self, units: float) -> float:
        """
        Attempt to supply `units` from this node.
        Returns actual units supplied (may be less than requested).
        """
        if not self.active:
            return 0.0
        actual = min(units, self.capacity, self.inventory)
        self.inventory      -= actual
        self._total_supplied += actual
        return actual

    def replenish(self, units: float) -> None:
        """Add units to supplier inventory (e.g. manufacturing run complete)."""
        self.inventory = min(self.inventory + units, self.capacity * 3)

    def apply_disruption(self, factor: float) -> None:
        """Reduce effective capacity during a disruption event."""
        self._disrupted_steps += 1
        self.capacity = self.capacity * factor

    def restore(self, original_capacity: float) -> None:
        """Restore capacity after disruption clears."""
        self.capacity = original_capacity

    def snapshot(self) -> dict:
        return {
            "node_id":        self.node_id,
            "name":           self.name,
            "inventory":      round(self.inventory, 1),
            "capacity":       round(self.capacity, 1),
            "reliability":    self.reliability,
            "cost_per_unit":  self.cost_per_unit,
            "lead_time":      self.lead_time,
            "region":         self.region,
            "active":         self.active,
            "total_supplied": round(self._total_supplied, 1),
        } 