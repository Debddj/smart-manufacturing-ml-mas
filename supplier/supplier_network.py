"""
SupplierNetwork — the Decentralised Supplier Network from the architecture diagram.

Architecture position:
    SupplierDiscoveryAgent → Supplier Node Network ↔ Smart Contract Agreement

Manages a graph of supplier nodes, routes procurement requests,
and coordinates with ContractEngine for smart contract execution.
"""

from __future__ import annotations
from typing import List, Optional, Dict

from supplier.supplier_node import SupplierNode
from supplier.contract_engine import ContractEngine


class SupplierNetwork:
    """
    Decentralised network of supplier nodes.

    Provides routing logic to find the best combination of suppliers
    to fill a procurement request. Works with ContractEngine to
    formalise each supply agreement.
    """

    def __init__(self, nodes: Optional[List[SupplierNode]] = None):
        self._contract_engine = ContractEngine()

        if nodes is not None:
            self.nodes: Dict[str, SupplierNode] = {n.node_id: n for n in nodes}
        else:
            # Default network matching SupplierDiscoveryAgent pool
            self.nodes = {
                "SUP-001": SupplierNode("SUP-001", "FastSource Co",      100.0, 300.0, 0.95, 1.8, 1, "local"),
                "SUP-002": SupplierNode("SUP-002", "GlobalParts Ltd",    200.0, 400.0, 0.85, 1.4, 2, "regional"),
                "SUP-003": SupplierNode("SUP-003", "BudgetSupply Inc",    80.0, 250.0, 0.72, 0.9, 3, "remote"),
                "SUP-004": SupplierNode("SUP-004", "PremiumSource AG",   150.0, 350.0, 0.98, 2.5, 1, "local"),
                "SUP-005": SupplierNode("SUP-005", "ReliableGoods Corp", 100.0, 300.0, 0.88, 1.6, 2, "regional"),
            }

        self._procurement_log: List[dict] = []

    def procure(
        self,
        units_needed:  float,
        max_cost:      float = float("inf"),
        prefer_local:  bool  = True,
    ) -> dict:
        """
        Procure units_needed from the best available node(s).

        Strategy: sort by reliability × cost efficiency, then fill
        from top-ranked nodes until demand is met or exhausted.

        Returns:
            dict with keys: fulfilled, total_cost, contracts, nodes_used
        """
        active_nodes = [n for n in self.nodes.values() if n.active and n.inventory > 0]
        if not active_nodes:
            return {"fulfilled": 0.0, "total_cost": 0.0, "contracts": [], "nodes_used": []}

        # Sort: local first if preferred, then by reliability
        def score(node: SupplierNode) -> float:
            local_bonus = 0.2 if prefer_local and node.region == "local" else 0.0
            return node.reliability + local_bonus

        active_nodes.sort(key=score, reverse=True)

        fulfilled    = 0.0
        total_cost   = 0.0
        contracts    = []
        nodes_used   = []
        remaining    = units_needed

        for node in active_nodes:
            if remaining <= 0:
                break
            batch     = min(remaining, node.capacity)
            supplied  = node.supply(batch)
            cost      = supplied * node.cost_per_unit

            if total_cost + cost > max_cost:
                # Can only afford partial
                affordable = (max_cost - total_cost) / node.cost_per_unit
                supplied   = node.supply(min(affordable, supplied))
                cost       = supplied * node.cost_per_unit

            if supplied > 0:
                contract = self._contract_engine.issue_contract(
                    supplier_id=node.node_id,
                    units=supplied,
                    cost=cost,
                    lead_time=node.lead_time,
                )
                fulfilled  += supplied
                total_cost += cost
                remaining  -= supplied
                contracts.append(contract)
                nodes_used.append(node.node_id)

        record = {
            "units_requested": round(units_needed, 1),
            "units_fulfilled": round(fulfilled,    1),
            "total_cost":      round(total_cost,   2),
            "nodes_used":      nodes_used,
            "fill_rate":       round(fulfilled / max(units_needed, 1e-9), 4),
        }
        self._procurement_log.append(record)
        return record

    def total_capacity(self) -> float:
        return sum(n.capacity for n in self.nodes.values() if n.active)

    def snapshot(self) -> dict:
        return {
            "nodes":             {nid: n.snapshot() for nid, n in self.nodes.items()},
            "total_capacity":    round(self.total_capacity(), 1),
            "procurement_count": len(self._procurement_log),
            "contracts_total":   self._contract_engine.contract_count,
        }

    def reset(self) -> None:
        for node in self.nodes.values():
            node.inventory = node.capacity * 2
            node._total_supplied  = 0.0
            node._disrupted_steps = 0
            node.active = True
        self._procurement_log.clear()
        self._contract_engine.reset() 