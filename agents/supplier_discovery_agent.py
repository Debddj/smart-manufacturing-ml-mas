"""
SupplierDiscoveryAgent — activated on the NO path from Inventory Available?.

Architecture position:
    Inventory Available? → NO → SupplierDiscoveryAgent
                                      → Supplier Node Network
                                      → Smart Contract Agreement

Responsibilities:
    - Maintain a pool of alternative supplier nodes
    - Score suppliers by reliability, capacity, and cost
    - Select optimal supplier for emergency procurement
    - Interface with ContractEngine for smart contract execution
"""

from __future__ import annotations
import random
from typing import List, Optional, Dict


# Supplier pool — realistic diversity of supplier types
DEFAULT_SUPPLIER_POOL = [
    {"id": "SUP-001", "name": "FastSource Co",      "capacity": 120.0, "reliability": 0.95,
     "cost_per_unit": 1.8,  "lead_time": 1, "region": "local"},
    {"id": "SUP-002", "name": "GlobalParts Ltd",    "capacity": 200.0, "reliability": 0.85,
     "cost_per_unit": 1.4,  "lead_time": 2, "region": "regional"},
    {"id": "SUP-003", "name": "BudgetSupply Inc",   "capacity": 80.0,  "reliability": 0.72,
     "cost_per_unit": 0.9,  "lead_time": 3, "region": "remote"},
    {"id": "SUP-004", "name": "PremiumSource AG",   "capacity": 150.0, "reliability": 0.98,
     "cost_per_unit": 2.5,  "lead_time": 1, "region": "local"},
    {"id": "SUP-005", "name": "ReliableGoods Corp", "capacity": 100.0, "reliability": 0.88,
     "cost_per_unit": 1.6,  "lead_time": 2, "region": "regional"},
]


class SupplierDiscoveryAgent:
    """
    Discovers and scores alternative suppliers when internal stock is depleted.

    Scoring model:
        score = (reliability × 0.4)
              + (capacity_coverage × 0.35)   # fraction of demand covered
              + (cost_efficiency × 0.25)     # inverse of cost relative to baseline

    The highest-scoring available supplier is selected.
    Disruptions reduce the reliability of certain supplier regions.
    """

    BASELINE_COST = 1.5   # cost per unit for primary supplier under normal conditions

    def __init__(
        self,
        supplier_pool: Optional[List[dict]] = None,
        agent_name:    str = "SupplierDiscoveryAgent",
    ):
        self.name          = agent_name
        self.supplier_pool = [s.copy() for s in (supplier_pool or DEFAULT_SUPPLIER_POOL)]

        # Episode tracking
        self.discovery_count:  int        = 0
        self.contracts_issued: int        = 0
        self.history:          List[dict] = []

    def find_supplier(
        self,
        units_needed: float,
        disruptions:  Optional[list] = None,
    ) -> Optional[dict]:
        """
        Find the best available alternative supplier.

        Args:
            units_needed: units required for emergency procurement
            disruptions:  active disruption types (affects regional reliability)

        Returns:
            Supplier dict with score and decision metadata, or None if none found.
        """
        self.discovery_count += 1
        active = set(disruptions or [])

        scored = []
        for supplier in self.supplier_pool:
            rel = supplier["reliability"]

            # Disruptions degrade remote/regional suppliers more
            if "supplier_failure" in active:
                if supplier["region"] == "remote":
                    rel *= 0.40
                elif supplier["region"] == "regional":
                    rel *= 0.70

            capacity_coverage = min(supplier["capacity"] / max(units_needed, 1.0), 1.0)
            cost_efficiency   = self.BASELINE_COST / max(supplier["cost_per_unit"], 0.01)
            cost_efficiency   = min(cost_efficiency, 1.0)

            score = (rel * 0.40 + capacity_coverage * 0.35 + cost_efficiency * 0.25)

            scored.append({
                **supplier,
                "effective_reliability": round(rel, 3),
                "capacity_coverage":     round(capacity_coverage, 3),
                "cost_efficiency":       round(cost_efficiency, 3),
                "score":                 round(score, 4),
                "units_needed":          round(units_needed, 1),
            })

        if not scored:
            return None

        scored.sort(key=lambda s: -s["score"])
        best = scored[0]

        # Availability check — stochastic based on reliability
        if random.random() > best["effective_reliability"]:
            return None   # supplier unavailable

        self.contracts_issued += 1
        self.history.append({
            "discovery_count": self.discovery_count,
            "selected":        best["id"],
            "score":           best["score"],
            "units_needed":    round(units_needed, 1),
        })

        return best

    def snapshot(self) -> dict:
        return {
            "discovery_count":  self.discovery_count,
            "contracts_issued": self.contracts_issued,
            "success_rate":     round(
                self.contracts_issued / max(self.discovery_count, 1), 3),
            "supplier_pool_size": len(self.supplier_pool),
        }

    def reset(self) -> None:
        self.discovery_count  = 0
        self.contracts_issued = 0
        self.history          = [] 