"""
InventoryAgent — global view across all warehouse nodes.

Wraps WarehouseNetwork and acts as the decision-maker for demand routing.
Communicates its decisions to other agents via the MessageBus.

Responsibilities:
    - Maintain a global view of inventory across all nodes
    - Evaluate each demand event and choose Branch A, B, or C
    - Publish branch decisions and inventory status to the MessageBus
    - Track fulfilment history for RL feedback

Branch logic:
    A: primary node has sufficient stock → fulfil directly
    B: primary node empty, another node has stock → inter-warehouse transfer
    C: all nodes depleted → signal external sourcing required

This agent is stateful within a simulation episode. Call reset() at the
start of each episode to clear history without losing node configuration.

Usage:
    from communication.message_bus import MessageBus
    from warehouse.warehouse_network import WarehouseNetwork

    bus     = MessageBus()
    network = WarehouseNetwork()
    agent   = InventoryAgent(network=network, bus=bus)

    # Register listeners before simulation starts
    agent.register_subscriptions()

    # Each simulation step:
    decision = agent.evaluate_and_route(
        demand        = 82.0,
        customer_zone = "A",
        step          = day,
    )
    # decision["branch"] in {"A", "B", "C"}
    # decision["units_fulfilled"] is how many were dispatched this step

    # After production arrives:
    agent.receive_production(node_id="A", units=80.0)
"""

from __future__ import annotations

from typing import Dict, List, Optional

from warehouse.warehouse_network import WarehouseNetwork, BRANCH_A, BRANCH_B, BRANCH_C
from communication.message_bus   import MessageBus, MessageType, Priority


# ── Default thresholds ────────────────────────────────────────────────────────

SAFETY_STOCK_UNITS = 20.0   # below this, WarehouseAgent publishes a WARNING
CRITICAL_STOCK     = 5.0    # below this, publishes ALERT


class InventoryAgent:
    """
    Autonomous agent with a global view of all warehouse inventory.

    The agent does not manage production scheduling (that is the RL agent's
    job). It exclusively handles demand routing — deciding which warehouse
    node should fulfil each demand event and coordinating any inter-node
    transfers required.

    State tracked per episode:
        branch_counts  : {"A": int, "B": int, "C": int}
        transfer_total : cumulative units transferred between nodes
        shortfall_total: cumulative units that could not be fulfilled
        step_log       : lightweight per-step record for RL feedback
    """

    def __init__(
        self,
        network:       Optional[WarehouseNetwork] = None,
        bus:           Optional[MessageBus] = None,
        customer_zone: str   = "A",
        safety_stock:  float = SAFETY_STOCK_UNITS,
        critical_stock:float = CRITICAL_STOCK,
        agent_name:    str   = "InventoryAgent",
    ):
        self.network       = network or WarehouseNetwork()
        self.bus           = bus
        self.customer_zone = customer_zone
        self.safety_stock  = safety_stock
        self.critical_stock= critical_stock
        self.name          = agent_name

        # Episode-level tracking
        self.branch_counts:   Dict[str, int] = {"A": 0, "B": 0, "C": 0}
        self.transfer_total:  float          = 0.0
        self.shortfall_total: float          = 0.0
        self.step_log:        List[dict]     = []

        # Previous inventory snapshot for change detection
        self._prev_inventory: Dict[str, float] = {}

    # ── Subscription setup ────────────────────────────────────────────────────

    def register_subscriptions(self) -> None:
        """
        Subscribe to relevant message types on the bus.
        Call once at agent startup before the simulation loop begins.
        Idempotent — safe to call multiple times.
        """
        if self.bus is None:
            return
        self.bus.subscribe(MessageType.STOCK_RISK,        self.on_stock_risk)
        self.bus.subscribe(MessageType.DEMAND_ADJUSTMENT, self.on_demand_adjustment)
        self.bus.subscribe(MessageType.POLICY_UPDATE,     self.on_policy_update)

    # ── Message handlers ──────────────────────────────────────────────────────

    def on_stock_risk(self, message) -> None:
        """
        Respond to DisruptionEngine STOCK_RISK alerts.
        Logs the risk internally. In a full system this would trigger
        a pre-emptive inventory transfer from unaffected nodes.
        """
        disruption = message.payload.get("disruption_type", "unknown")
        self.step_log.append({
            "step":    message.step,
            "event":   "stock_risk_received",
            "from":    message.sender,
            "detail":  f"Disruption '{disruption}' flagged — monitoring inventory levels",
        })

    def on_demand_adjustment(self, message) -> None:
        """
        Respond to demand surge alerts by noting elevated risk.
        Inventory agent notes the surge; production decisions remain
        with the RL agent.
        """
        self.step_log.append({
            "step":   message.step,
            "event":  "demand_adjustment_received",
            "from":   message.sender,
            "detail": f"Demand adjustment signal received — buffer risk elevated",
        })

    def on_policy_update(self, message) -> None:
        """
        Receive updated routing policy from the Q-Agent.
        Currently records the update for diagnostics. Future versions
        will apply preferred_node hints from the policy dict.
        """
        self.step_log.append({
            "step":   message.step,
            "event":  "policy_update_received",
            "from":   message.sender,
            "detail": f"Routing policy updated by RL agent",
        })

    # ── Core routing decision ─────────────────────────────────────────────────

    def evaluate_and_route(
        self,
        demand:        float,
        customer_zone: Optional[str] = None,
        step:          int = 0,
    ) -> dict:
        """
        Main entry point — evaluate demand and execute the routing decision.

        1. Ask WarehouseNetwork which branch applies
        2. Execute the fulfilment (dispatch or initiate transfer)
        3. Publish the decision to the MessageBus
        4. Publish inventory status update
        5. Return a result dict for the simulation runner

        Returns:
        {
            "branch":           "A" | "B" | "C",
            "units_fulfilled":  float,
            "units_transferred":float,
            "shortfall":        float,
            "source_node":      str or None,
            "decision":         full decision dict from WarehouseNetwork,
        }
        """
        zone     = customer_zone or self.customer_zone
        decision = self.network.evaluate_demand(
            units_needed  = demand,
            customer_zone = zone,
            min_safety    = self.safety_stock,
        )
        branch        = decision["branch"]
        units_fulfilled  = 0.0
        units_transferred= 0.0

        # ── Execute branch ────────────────────────────────────────────────────
        if branch == BRANCH_A:
            units_fulfilled = self.network.fulfil(decision["source"], demand)

        elif branch == BRANCH_B:
            units_transferred = self.network.execute_transfer(
                decision["transfer_from"],
                decision["transfer_to"],
                demand,
            )
            # Fulfil from current primary stock (transferred units arrive later)
            available = self.network.nodes[zone].inventory
            units_fulfilled = self.network.fulfil(zone, min(demand, available))

        else:  # BRANCH_C — system depleted
            for node in self.network.nodes.values():
                got = node.dispatch(min(node.inventory, demand - units_fulfilled))
                units_fulfilled += got
                if units_fulfilled >= demand:
                    break

        units_fulfilled   = min(units_fulfilled, demand)
        shortfall         = max(0.0, demand - units_fulfilled)

        # ── Update episode tracking ───────────────────────────────────────────
        self.branch_counts[branch]  = self.branch_counts.get(branch, 0) + 1
        self.transfer_total        += units_transferred
        self.shortfall_total       += shortfall

        # ── Publish to bus ────────────────────────────────────────────────────
        if self.bus is not None:
            # Branch decision
            self.bus.publish_branch_decision(
                sender   = self.name,
                branch   = branch,
                decision = {
                    "units_fulfilled":   round(units_fulfilled, 2),
                    "units_transferred": round(units_transferred, 2),
                    "shortfall":         round(shortfall, 2),
                    "demand":            round(demand, 2),
                },
                step = step,
            )

            # Inventory status for primary node
            primary = self.network.nodes.get(zone)
            if primary:
                self.bus.publish_inventory_status(
                    sender    = self.name,
                    node_id   = zone,
                    inventory = primary.inventory,
                    capacity  = primary.capacity,
                    step      = step,
                )

            # Critical stock alert
            if primary and primary.inventory < self.critical_stock:
                self.bus.publish(
                    message_type = MessageType.STOCK_RISK,
                    sender       = self.name,
                    payload      = {
                        "node_id":    zone,
                        "inventory":  round(primary.inventory, 2),
                        "threshold":  self.critical_stock,
                        "severity":   "CRITICAL",
                    },
                    priority = Priority.ALERT,
                    step     = step,
                )

        return {
            "branch":            branch,
            "units_fulfilled":   round(units_fulfilled,   2),
            "units_transferred": round(units_transferred, 2),
            "shortfall":         round(shortfall,         2),
            "source_node":       decision.get("source"),
            "decision":          decision,
        }

    # ── Production interface ──────────────────────────────────────────────────

    def receive_production(self, node_id: str, units: float) -> None:
        """
        Direct newly produced units to a warehouse node.
        Called by simulation runner after the RL agent decides production qty.
        """
        self.network.receive_production(node_id, units)

    def receive_production_balanced(self, units: float) -> None:
        """
        Distribute production across nodes proportional to their deficit.
        Alternative to direct allocation — balances inventory across nodes.
        """
        self.network.receive_production_balanced(units)

    # ── Step advancement ──────────────────────────────────────────────────────

    def tick(self) -> dict:
        """
        Advance one simulation step.
        Processes all inbound inter-warehouse transfers.
        Returns dict of units that arrived per node this step.
        """
        return self.network.tick()

    # ── State accessors ───────────────────────────────────────────────────────

    @property
    def total_inventory(self) -> float:
        return self.network.total_inventory()

    @property
    def primary_inventory(self) -> float:
        node = self.network.nodes.get(self.customer_zone)
        return node.inventory if node else 0.0

    def inventory_vector(self) -> list:
        """Returns [wh_A, wh_B, wh_C] sorted — compatible with DQNAgent.build_state()."""
        return self.network.inventory_vector()

    def snapshot(self) -> dict:
        """Full state snapshot for dashboard and diagnostics."""
        return {
            "network":         self.network.snapshot(),
            "branch_counts":   dict(self.branch_counts),
            "transfer_total":  round(self.transfer_total,   2),
            "shortfall_total": round(self.shortfall_total,  2),
            "step_log_size":   len(self.step_log),
            "branch_a_pct":    self._branch_pct("A"),
            "branch_b_pct":    self._branch_pct("B"),
            "branch_c_pct":    self._branch_pct("C"),
        }

    def _branch_pct(self, branch: str) -> float:
        total = sum(self.branch_counts.values())
        if total == 0:
            return 0.0
        return round(self.branch_counts.get(branch, 0) / total * 100, 1)

    # ── Reset ─────────────────────────────────────────────────────────────────

    def reset(self, initial_inventory: float = 100.0) -> None:
        """Reset for a new training episode. Preserves node configuration."""
        self.network.reset(initial_inventory)
        self.branch_counts   = {"A": 0, "B": 0, "C": 0}
        self.transfer_total  = 0.0
        self.shortfall_total = 0.0
        self.step_log        = []
        self._prev_inventory = {} 