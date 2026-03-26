"""
Supply chain environments.

Two classes:
    SupplyChainEnvironment    — original single-warehouse (backward compatible)
    MultiWarehouseEnvironment — 3-warehouse with Branch A/B/C routing

Both expose the same step() interface so simulation_runner.py can
switch between them with minimal changes.

FIXES APPLIED:
    1. 'import math' moved from inside get_state_vector() to module level.
       Importing inside a method works but re-imports on every call —
       bad practice and confusing to read.
"""

from __future__ import annotations
import math

from warehouse.warehouse_network import WarehouseNetwork, BRANCH_A, BRANCH_B, BRANCH_C


# ── Original single-warehouse environment (unchanged — backward compatible) ───

class SupplyChainEnvironment:
    """
    Original single-warehouse environment.
    Kept intact so existing simulation_runner.py works without modification.
    """

    def __init__(self):
        self.inventory     = 100
        self.max_inventory = 300
        self.cost          = 0

    def step(self, production, shipment, demand):
        self.inventory += production
        self.inventory  = min(self.inventory, self.max_inventory)

        shipment        = min(shipment, self.inventory)
        self.inventory -= shipment

        satisfied = min(shipment, demand)
        delay     = max(0, demand - satisfied)

        cost = (
            production     * 1.0
            + self.inventory * 0.5
            + delay          * 5
        )
        self.cost += cost
        return satisfied, cost, delay


# ── Multi-warehouse environment ────────────────────────────────────────────────

class MultiWarehouseEnvironment:
    """
    Three-warehouse supply chain environment.

    step() returns (satisfied, cost, delay, branch, transfer_units).
    The first three values are identical to SupplyChainEnvironment.step()
    for backward compatibility.

    Branch B behaviour: units are immediately removed from the donor node
    and queued as an inbound transfer to the primary node. The primary node
    can only fulfil from its current local stock this step; the transferred
    units arrive after donor_node.transfer_time steps. This means Branch B
    steps will show partial fulfilment — this is correct and intentional.

    Cost model:
        production_cost = units_produced  × 1.0
        holding_cost    = total_inventory × 0.3
        delay_cost      = unmet_demand    × 5.0
        transfer_cost   = units_transferred × 2.0 (default per node)
    """

    PRODUCTION_COST_PER_UNIT = 1.0
    HOLDING_COST_PER_UNIT    = 0.3
    DELAY_COST_PER_UNIT      = 5.0
    TRANSFER_COST_PER_UNIT   = 2.0

    def __init__(
        self,
        customer_zone:     str   = "A",
        initial_inventory: float = 100.0,
        safety_stock:      float = 20.0,
    ):
        self.network       = WarehouseNetwork()
        self.network.reset(initial_inventory)
        self.customer_zone = customer_zone
        self.safety_stock  = safety_stock
        self.cost          = 0.0

        self._last_branch   = BRANCH_A
        self._last_transfer = 0.0

    # ── Backward-compatible inventory property ────────────────────────────────

    @property
    def inventory(self) -> float:
        """Primary warehouse inventory — backward-compatible single value read."""
        primary = self.network.nodes.get(
            self.customer_zone,
            list(self.network.nodes.values())[0]
        )
        return primary.inventory

    @property
    def max_inventory(self) -> float:
        """Returns primary node capacity for backward compatibility."""
        primary = self.network.nodes.get(
            self.customer_zone,
            list(self.network.nodes.values())[0]
        )
        return primary.capacity

    # ── Core step ─────────────────────────────────────────────────────────────

    def step(
        self,
        production:       float,
        shipment:         float,
        demand:           float,
        production_node:  str  = "A",
        disruption_types: list = None,
    ) -> tuple:
        """
        Advance one simulation step.

        Returns:
            (satisfied, cost, delay, branch, transfer_units)

        First three values match SupplyChainEnvironment.step() exactly.
        """
        # 1. Advance inbound transfers from previous steps
        self.network.tick()

        # 2. Allocate production to the designated node
        if production > 0:
            self.network.receive_production(production_node, production)

        # 3. Branch decision
        decision = self.network.evaluate_demand(
            demand,
            customer_zone=self.customer_zone,
        )
        branch   = decision["branch"]
        transfer = 0.0

        if branch == BRANCH_A:
            satisfied = self.network.fulfil(decision["source"], demand)

        elif branch == BRANCH_B:
            # Initiate transfer from donor — units arrive after transfer_time steps
            transfer = self.network.execute_transfer(
                decision["transfer_from"],
                decision["transfer_to"],
                demand,
            )
            # Fulfil only from what the primary node has right now
            available_now = self.network.nodes[self.customer_zone].inventory
            satisfied     = self.network.fulfil(
                self.customer_zone, min(demand, available_now)
            )

        else:  # BRANCH_C — all nodes depleted
            satisfied = 0.0
            for node in self.network.nodes.values():
                got = node.dispatch(min(node.inventory, demand - satisfied))
                satisfied += got
                if satisfied >= demand:
                    break

        satisfied = min(satisfied, demand)
        delay     = max(0.0, demand - satisfied)

        # 4. Cost
        total_inv = self.network.total_inventory()
        cost = (
            production * self.PRODUCTION_COST_PER_UNIT
            + total_inv  * self.HOLDING_COST_PER_UNIT
            + delay      * self.DELAY_COST_PER_UNIT
            + transfer   * self.TRANSFER_COST_PER_UNIT
        )
        self.cost += cost

        self._last_branch   = branch
        self._last_transfer = transfer

        return satisfied, cost, delay, branch, transfer

    # ── State vector for DQN ──────────────────────────────────────────────────

    def get_state_vector(
        self,
        demand:               float,
        active_disruptions:   list  = None,
        supplier_reliability: float = 1.0,
        day:                  int   = 0,
    ) -> list:
        """
        Build the 10-dimensional normalised state vector for DQNAgent.
        Call after step() to get the post-action state.

        FIX: math is now imported at module level (was imported inside this
        method on every call — wasteful and bad practice).
        """
        inv_vec = self.network.inventory_vector()   # [A, B, C] sorted
        active  = set(active_disruptions or [])
        MAX_INV = 300.0
        MAX_DEM = 250.0

        return [
            inv_vec[0] / MAX_INV,
            inv_vec[1] / MAX_INV,
            inv_vec[2] / MAX_INV,
            min(demand / MAX_DEM, 1.0),
            1.0 if "supplier_failure"     in active else 0.0,
            1.0 if "demand_surge"         in active else 0.0,
            1.0 if "logistics_breakdown"  in active else 0.0,
            1.0 if "factory_slowdown"     in active else 0.0,
            float(max(0.0, min(1.0, supplier_reliability))),
            float(math.sin(2 * math.pi * (day % 7) / 7)),
        ]

    # ── Reset ─────────────────────────────────────────────────────────────────

    def reset(self, initial_inventory: float = 100.0):
        self.network.reset(initial_inventory)
        self.cost           = 0.0
        self._last_branch   = BRANCH_A
        self._last_transfer = 0.0

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        return {
            "network":       self.network.snapshot(),
            "total_cost":    round(self.cost, 2),
            "last_branch":   self._last_branch,
            "last_transfer": round(self._last_transfer, 2),
        }