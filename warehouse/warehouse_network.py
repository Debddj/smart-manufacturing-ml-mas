"""
Multi-warehouse infrastructure for the upscaled supply chain.

Two classes:
    WarehouseNode    — a single physical warehouse
    WarehouseNetwork — global view; makes Branch A/B/C decisions

Branch logic:
    A: local node near customer has sufficient stock → fulfil directly
    B: local node empty, another node has stock → inter-warehouse transfer
    C: all nodes depleted → trigger external sourcing (returns STOCKOUT)

FIXES APPLIED:
    1. _find_best_donor relaxation condition was 'nid == exclude_id'
       (added back the EXCLUDED node). Fixed to 'nid != exclude_id'.
    2. WarehouseNode._inbound field now has init=False so simple
       WarehouseNode("A") instantiation works without passing _inbound.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List


# ── Single warehouse node ─────────────────────────────────────────────────────

@dataclass
class WarehouseNode:
    """
    Single physical warehouse.

    Attributes:
        node_id        : identifier, e.g. "A", "B", "C"
        inventory      : current stock level (units)
        capacity       : maximum storage (units)
        location_zone  : geographic zone label for logistics cost lookup
        transfer_cost  : cost per unit to move inventory TO another node
        transfer_time  : steps to complete an inter-warehouse transfer
    """
    node_id:       str
    inventory:     float = 100.0
    capacity:      float = 300.0
    location_zone: str   = "default"
    transfer_cost: float = 2.0
    transfer_time: int   = 2

    # FIX: init=False prevents _inbound appearing in __init__ signature.
    # Without this, WarehouseNode("A") raises TypeError: missing argument '_inbound'
    _inbound: list = field(default_factory=list, repr=False, init=False)

    def receive(self, units: float):
        """Add production or transferred units to inventory."""
        self.inventory = min(self.inventory + units, self.capacity)

    def dispatch(self, units: float) -> float:
        """
        Remove units from inventory.
        Returns actual dispatched (may be less if insufficient stock).
        """
        dispatched     = min(self.inventory, units)
        self.inventory -= dispatched
        return dispatched

    def initiate_transfer_out(self, units: float) -> float:
        """Lock units for outbound transfer. Returns actual units locked."""
        locked         = min(self.inventory, units)
        self.inventory -= locked
        return locked

    def queue_inbound(self, units: float, steps: int):
        """Register an incoming transfer arriving after `steps` steps."""
        self._inbound.append([units, steps])

    def tick_inbound(self) -> float:
        """
        Advance inbound transfer timers by one step.
        Returns units that arrived this step.
        """
        arrived   = 0.0
        remaining = []
        for units, steps_left in self._inbound:
            if steps_left <= 1:
                arrived += units
            else:
                remaining.append([units, steps_left - 1])
        self._inbound = remaining
        if arrived > 0:
            self.receive(arrived)
        return arrived

    @property
    def fill_ratio(self) -> float:
        return self.inventory / self.capacity if self.capacity > 0 else 0.0

    def snapshot(self) -> dict:
        return {
            "node_id":          self.node_id,
            "inventory":        round(self.inventory, 2),
            "capacity":         self.capacity,
            "fill_ratio":       round(self.fill_ratio, 3),
            "inbound_pending":  sum(u for u, _ in self._inbound),
        }


# ── Network of warehouses ─────────────────────────────────────────────────────

BRANCH_A = "A"   # local fulfilment
BRANCH_B = "B"   # inter-warehouse transfer
BRANCH_C = "C"   # external sourcing required (stockout internally)


class WarehouseNetwork:
    """
    Global inventory view across all warehouse nodes.

    Manages:
        - Production allocation (which node receives new units)
        - Branch A / B / C decision for each demand event
        - Inter-warehouse transfer orchestration
        - Per-node inbound transfer ticking

    Default: three nodes A (primary), B (secondary), C (bulk reserve).
    """

    def __init__(self, nodes: Optional[list] = None):
        if nodes is None:
            nodes = [
                WarehouseNode("A", inventory=100.0, capacity=300.0,
                              location_zone="primary",   transfer_cost=2.0, transfer_time=1),
                WarehouseNode("B", inventory=80.0,  capacity=300.0,
                              location_zone="secondary", transfer_cost=3.0, transfer_time=2),
                WarehouseNode("C", inventory=120.0, capacity=500.0,
                              location_zone="bulk",      transfer_cost=1.5, transfer_time=3),
            ]
        self.nodes: dict[str, WarehouseNode] = {n.node_id: n for n in nodes}
        self._transfer_log: list[dict] = []

    # ── Core branch decision ──────────────────────────────────────────────────

    def evaluate_demand(
        self,
        units_needed:  float,
        customer_zone: str   = "A",
        min_safety:    float = 20.0,
    ) -> dict:
        """
        Determine how to fulfil a demand of `units_needed`.

        Returns a decision dict:
        {
            "branch":            "A" | "B" | "C",
            "source":            node_id or None,
            "units_available":   float,
            "transfer_required": bool,
            "transfer_from":     node_id or None,
            "transfer_to":       node_id or None,
            "estimated_steps":   int,
            "reason":            str,
        }
        """
        primary_id = (customer_zone if customer_zone in self.nodes
                      else list(self.nodes.keys())[0])
        primary    = self.nodes[primary_id]

        # Branch A: primary node has enough stock
        if primary.inventory >= units_needed:
            return {
                "branch":            BRANCH_A,
                "source":            primary_id,
                "units_available":   primary.inventory,
                "transfer_required": False,
                "transfer_from":     None,
                "transfer_to":       None,
                "estimated_steps":   0,
                "reason":            (f"Node {primary_id} has "
                                      f"{primary.inventory:.0f} units locally"),
            }

        # Branch B: search other nodes for stock
        best_donor = self._find_best_donor(
            exclude_id  = primary_id,
            units_needed = units_needed,
            min_safety  = min_safety,
        )
        if best_donor:
            donor_node = self.nodes[best_donor]
            return {
                "branch":            BRANCH_B,
                "source":            best_donor,
                "units_available":   donor_node.inventory,
                "transfer_required": True,
                "transfer_from":     best_donor,
                "transfer_to":       primary_id,
                "estimated_steps":   donor_node.transfer_time,
                "reason":            (f"Node {best_donor} has "
                                      f"{donor_node.inventory:.0f} units; "
                                      f"transferring to {primary_id}"),
            }

        # Branch C: system depleted
        total = self.total_inventory()
        return {
            "branch":            BRANCH_C,
            "source":            None,
            "units_available":   total,
            "transfer_required": False,
            "transfer_from":     None,
            "transfer_to":       None,
            "estimated_steps":   0,
            "reason":            (f"All nodes depleted "
                                  f"(total {total:.0f} units); external sourcing needed"),
        }

    def _find_best_donor(
        self,
        exclude_id:   str,
        units_needed: float,
        min_safety:   float,
    ) -> Optional[str]:
        """
        Select the best donor node for an inter-warehouse transfer.
        Preference: highest surplus above safety stock, then lowest transfer cost.

        FIX: relaxation condition was 'nid == exclude_id' (wrong — added back
        the excluded node). Corrected to 'nid != exclude_id'.
        """
        candidates = []
        for nid, node in self.nodes.items():
            if nid == exclude_id:
                continue
            surplus = node.inventory - min_safety
            if surplus >= units_needed:
                candidates.append((nid, surplus, node.transfer_cost))

        if not candidates:
            # Relax: any non-excluded node with any stock at all
            for nid, node in self.nodes.items():
                # FIX: was 'nid == exclude_id' — should be 'nid != exclude_id'
                if nid != exclude_id and node.inventory > 0:
                    candidates.append((nid, node.inventory, node.transfer_cost))

        if not candidates:
            return None

        # Sort: prefer highest surplus, then cheapest transfer
        candidates.sort(key=lambda x: (-x[1], x[2]))
        return candidates[0][0]

    # ── Production allocation ──────────────────────────────────────────────────

    def receive_production(self, node_id: str, units: float):
        """Direct new production units to a specific warehouse node."""
        if node_id in self.nodes:
            self.nodes[node_id].receive(units)

    def receive_production_balanced(self, units: float):
        """
        Distribute production inversely proportional to fill ratio.
        Nodes with lower fill ratios receive more of the batch.
        """
        fill_ratios   = {nid: node.fill_ratio for nid, node in self.nodes.items()}
        total_deficit = sum(1.0 - r for r in fill_ratios.values())
        if total_deficit == 0:
            target = min(self.nodes.keys(), key=lambda k: self.nodes[k].fill_ratio)
            self.nodes[target].receive(units)
            return
        for nid, node in self.nodes.items():
            share = (1.0 - fill_ratios[nid]) / total_deficit
            node.receive(units * share)

    # ── Transfer execution ─────────────────────────────────────────────────────

    def execute_transfer(self, from_id: str, to_id: str, units: float) -> float:
        """
        Initiate an inter-warehouse transfer.
        Units are immediately removed from `from_id` and queued for `to_id`.
        Returns actual units transferred.
        """
        if from_id not in self.nodes or to_id not in self.nodes:
            return 0.0
        src  = self.nodes[from_id]
        dst  = self.nodes[to_id]
        sent = src.initiate_transfer_out(units)
        if sent > 0:
            dst.queue_inbound(sent, src.transfer_time)
            self._transfer_log.append({
                "from":      from_id,
                "to":        to_id,
                "units":     sent,
                "eta_steps": src.transfer_time,
            })
        return sent

    # ── Fulfilment execution ───────────────────────────────────────────────────

    def fulfil(self, node_id: str, units: float) -> float:
        """Dispatch units from a specific node. Returns actual dispatched."""
        if node_id not in self.nodes:
            return 0.0
        return self.nodes[node_id].dispatch(units)

    # ── Step advancement ───────────────────────────────────────────────────────

    def tick(self) -> dict:
        """
        Advance all nodes by one time step.
        Processes inbound transfers. Returns dict of units arrived per node.
        """
        arrived = {}
        for nid, node in self.nodes.items():
            a = node.tick_inbound()
            if a > 0:
                arrived[nid] = a
        return arrived

    # ── Aggregates ─────────────────────────────────────────────────────────────

    def total_inventory(self) -> float:
        return sum(n.inventory for n in self.nodes.values())

    def inventory_vector(self) -> List[float]:
        """Returns [wh_A_inv, wh_B_inv, wh_C_inv] in sorted node_id order."""
        return [self.nodes[k].inventory for k in sorted(self.nodes.keys())]

    def snapshot(self) -> dict:
        return {
            "nodes":             {nid: n.snapshot() for nid, n in self.nodes.items()},
            "total_inventory":   round(self.total_inventory(), 2),
            "transfer_log_size": len(self._transfer_log),
        }

    def reset(self, initial_inventory: float = 100.0):
        """Reset all nodes for a new training episode."""
        for node in self.nodes.values():
            node.inventory = initial_inventory
            node._inbound  = []
        self._transfer_log.clear()