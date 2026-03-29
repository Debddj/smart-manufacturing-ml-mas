"""
LastMileAgent — final delivery hop to the customer.

Architecture position:
    FulfillmentAgent → LastMileDeliveryAgent → Customer Delivery

CHANGE: Added MAX_HISTORY cap (1000 entries) as a safety net.
The primary fix is in simulation_runner.py which now calls reset() at the start
of each episode. This cap prevents any future regression from causing OOM.
"""

from __future__ import annotations
from typing import List, Optional

ROUTES = ["express", "standard", "economy"]
ROUTE_CAPACITY = {"express": 150.0, "standard": 300.0, "economy": 500.0}
ROUTE_COST     = {"express": 3.0,   "standard": 1.5,   "economy": 0.8}

MAX_HISTORY = 1000  # Safety cap — primary fix is reset() in simulation_runner


class LastMileAgent:
    """
    Simulates last-mile delivery from fulfilment centre to customer.

    Under normal conditions all confirmed units are delivered in the
    same step. Under logistics_breakdown the effective delivery capacity
    is reduced, creating additional delay even after warehouse dispatch.
    """

    def __init__(self, agent_name: str = "LastMileDeliveryAgent"):
        self.name = agent_name

        # Episode tracking
        self.total_delivered:    float = 0.0
        self.on_time_deliveries: int   = 0
        self.late_deliveries:    int   = 0
        self._step_count:        int   = 0
        self.history:            List[dict] = []

    def deliver(
        self,
        units:       float,
        step:        int   = 0,
        disruptions: Optional[list] = None,
    ) -> dict:
        """
        Simulate last-mile delivery for confirmed units.

        Returns:
            dict with keys: delivered, route, on_time, units, cost
        """
        self._step_count += 1
        active = set(disruptions or [])

        if units <= 150:
            route = "express"
        elif units <= 300:
            route = "standard"
        else:
            route = "economy"

        capacity = ROUTE_CAPACITY[route]
        if "logistics_breakdown" in active:
            capacity *= 0.20

        delivered = min(units, capacity)
        on_time   = delivered >= units * 0.95

        if on_time:
            self.on_time_deliveries += 1
        else:
            self.late_deliveries += 1

        self.total_delivered += delivered

        record = {
            "step":      step,
            "units":     round(units,     1),
            "delivered": round(delivered, 1),
            "route":     route,
            "on_time":   on_time,
            "cost":      round(delivered * ROUTE_COST[route], 2),
            "disrupted": bool(active),
        }

        # Safety cap: only store recent history to prevent unbounded growth
        if len(self.history) < MAX_HISTORY:
            self.history.append(record)

        return record

    @property
    def on_time_rate(self) -> float:
        total = self.on_time_deliveries + self.late_deliveries
        if total == 0:
            return 1.0
        return round(self.on_time_deliveries / total, 4)

    def snapshot(self) -> dict:
        return {
            "total_delivered":    round(self.total_delivered, 1),
            "on_time_deliveries": self.on_time_deliveries,
            "late_deliveries":    self.late_deliveries,
            "on_time_rate":       self.on_time_rate,
            "step_count":         self._step_count,
        }

    def reset(self) -> None:
        self.total_delivered    = 0.0
        self.on_time_deliveries = 0
        self.late_deliveries    = 0
        self._step_count        = 0
        self.history            = []  