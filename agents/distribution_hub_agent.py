"""
DistributionHubAgent — Distribution Layer from the architecture diagram.

Architecture position:
    Logistics Agent → Distribution Hub Agent → Multi Warehouse System
                                             ↕ Inter-Warehouse Transfer

Responsibilities:
    - Coordinate inter-warehouse transfers (Branch B decisions)
    - Track distribution efficiency across Warehouse A, B, C
    - Publish routing decisions to the MessageBus
    - Monitor which warehouse nodes are under pressure
"""

from __future__ import annotations
from typing import List, Optional
from collections import defaultdict


class DistributionHubAgent:
    """
    Coordinates distribution across the multi-warehouse network.

    Operates as a thin orchestration layer: it does not make inventory
    decisions (that is the InventoryAgent's job) but it records and
    reports all routing decisions for the dashboard and RL feedback.
    """

    def __init__(self, agent_name: str = "DistributionHubAgent"):
        self.name = agent_name

        # Episode tracking
        self.branch_counts:      dict  = {"A": 0, "B": 0, "C": 0}
        self.transfer_history:   List[dict] = []
        self.total_transferred:  float = 0.0
        self._step_count:        int   = 0

        # Per-warehouse utilisation tracking
        self.warehouse_dispatch: dict  = defaultdict(float)

    def route(
        self,
        branch:         str,
        transfer_units: float = 0.0,
        warehouses:     Optional[List[str]] = None,
        step:           int   = 0,
    ) -> dict:
        """
        Record a routing decision made by InventoryAgent.

        Args:
            branch:         "A", "B", or "C"
            transfer_units: units moved inter-warehouse (Branch B only)
            warehouses:     list of warehouse IDs participating
            step:           simulation step

        Returns:
            routing summary dict
        """
        self._step_count += 1
        self.branch_counts[branch] = self.branch_counts.get(branch, 0) + 1
        self.total_transferred    += transfer_units

        record = {
            "step":           step,
            "branch":         branch,
            "transfer_units": round(transfer_units, 1),
            "warehouses":     warehouses or [],
        }
        if branch == "B":
            self.transfer_history.append(record)

        return record

    def preferred_warehouse(self) -> Optional[str]:
        """Returns the warehouse ID with most dispatches (primary node)."""
        if not self.warehouse_dispatch:
            return None
        return max(self.warehouse_dispatch, key=self.warehouse_dispatch.get)

    def branch_efficiency(self) -> dict:
        """Returns percentage of fulfilment handled per branch."""
        total = sum(self.branch_counts.values())
        if total == 0:
            return {"A": 0.0, "B": 0.0, "C": 0.0}
        return {k: round(v / total * 100, 1) for k, v in self.branch_counts.items()}

    def snapshot(self) -> dict:
        return {
            "branch_counts":      dict(self.branch_counts),
            "branch_efficiency":  self.branch_efficiency(),
            "total_transferred":  round(self.total_transferred, 1),
            "transfer_events":    len(self.transfer_history),
            "step_count":         self._step_count,
        }

    def reset(self) -> None:
        self.branch_counts     = {"A": 0, "B": 0, "C": 0}
        self.transfer_history  = []
        self.total_transferred = 0.0
        self._step_count       = 0
        self.warehouse_dispatch.clear()  