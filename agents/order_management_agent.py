"""
OrderManagementAgent — the orchestrator that coordinates all agents
to fulfil a customer demand event end-to-end.

In the original system the simulation_runner.py loop acts as an implicit
orchestrator — it sequences supplier → RL agent → warehouse → logistics
inside its for loop. The OrderManagementAgent makes that orchestration
explicit and traceable, with a formal state machine per order.

Order state machine:
    RECEIVED → INVENTORY_CHECK → SOURCING → IN_TRANSIT → DELIVERED → COMPLETE

    RECEIVED        : demand event registered
    INVENTORY_CHECK : InventoryAgent evaluating Branch A/B/C
    SOURCING        : Branch C only — external supplier being contacted
    IN_TRANSIT      : goods dispatched, en route to customer
    DELIVERED       : customer received goods
    COMPLETE        : feedback sent to RL agent, order closed
    FAILED          : could not fulfil — all options exhausted

Each state transition is published to the MessageBus so all agents
can react to order progress without polling.

Usage:
    oma = OrderManagementAgent(bus=bus, inventory_agent=inv_agent)

    # Process one demand event (matches one simulation step)
    result = oma.process_demand(
        demand      = 82.0,
        step        = day,
        production  = 80.0,
        transport   = 75.0,
    )
    # result["satisfied"]   — units actually delivered
    # result["order_id"]    — unique order reference
    # result["branch"]      — A / B / C
    # result["final_state"] — COMPLETE or FAILED
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from communication.message_bus import MessageBus, MessageType, Priority


# ── Order states ──────────────────────────────────────────────────────────────

class OrderState(str, Enum):
    RECEIVED        = "RECEIVED"
    INVENTORY_CHECK = "INVENTORY_CHECK"
    SOURCING        = "SOURCING"
    IN_TRANSIT      = "IN_TRANSIT"
    DELIVERED       = "DELIVERED"
    COMPLETE        = "COMPLETE"
    FAILED          = "FAILED"


# ── Order record ──────────────────────────────────────────────────────────────

@dataclass
class Order:
    """
    Immutable reference + mutable state record for one customer demand event.

    order_id     : unique identifier (short UUID prefix for readability)
    demand       : units requested
    step         : simulation step when order was created
    state        : current OrderState
    branch       : A / B / C routing decision
    satisfied    : units actually delivered to customer
    cost         : total cost incurred to fulfil this order
    delay        : units of unmet demand (backorder)
    transfer_units: units moved inter-warehouse for this order
    history      : list of (step, old_state, new_state) transitions
    """
    order_id:       str
    demand:         float
    step:           int
    state:          OrderState     = OrderState.RECEIVED
    branch:         str            = "?"
    satisfied:      float          = 0.0
    cost:           float          = 0.0
    delay:          float          = 0.0
    transfer_units: float          = 0.0
    history:        List[dict]     = field(default_factory=list)

    def transition(self, new_state: OrderState, step: int, detail: str = "") -> None:
        self.history.append({
            "step":      step,
            "old_state": self.state.value,
            "new_state": new_state.value,
            "detail":    detail,
        })
        self.state = new_state

    def to_dict(self) -> dict:
        return {
            "order_id":      self.order_id,
            "demand":        round(self.demand,   2),
            "step":          self.step,
            "state":         self.state.value,
            "branch":        self.branch,
            "satisfied":     round(self.satisfied, 2),
            "cost":          round(self.cost,      2),
            "delay":         round(self.delay,     2),
            "transfer_units":round(self.transfer_units, 2),
            "fill_rate":     round(self.satisfied / max(self.demand, 1e-9), 4),
            "transitions":   len(self.history),
        }


# ── Order management agent ────────────────────────────────────────────────────

class OrderManagementAgent:
    """
    Orchestrates end-to-end fulfilment for each demand event.

    In simulation mode (one step = one demand event) the agent processes
    the demand synchronously through the state machine within a single
    process_demand() call. In a real deployed system the state machine
    would be async, with each state persisted to a database.

    The agent communicates all state transitions to the MessageBus so
    any subscribed agent (Logistics, Procurement, Dashboard) can react.

    Episode-level tracking:
        orders              : dict of all Order objects keyed by order_id
        completed_orders    : subset that reached COMPLETE or FAILED
        total_satisfied     : cumulative units delivered
        total_demand        : cumulative demand received
        sla_breach_count    : orders where fill_rate < SLA threshold
    """

    SLA_FILL_RATE = 0.90

    def __init__(
        self,
        bus:             Optional[MessageBus] = None,
        inventory_agent = None,               # InventoryAgent instance
        sla_fill_rate:   float = 0.90,
        agent_name:      str   = "OrderManagementAgent",
    ):
        self.bus              = bus
        self.inventory_agent  = inventory_agent
        self.SLA_FILL_RATE    = sla_fill_rate
        self.name             = agent_name

        # Episode state
        self.orders:           Dict[str, Order] = {}
        self.completed_orders: List[Order]      = []
        self.total_satisfied:  float            = 0.0
        self.total_demand:     float            = 0.0
        self.sla_breach_count: int              = 0
        self._step_count:      int              = 0

    # ── Subscription setup ────────────────────────────────────────────────────

    def register_subscriptions(self) -> None:
        """
        Subscribe to relevant bus message types.
        Call once at agent startup.
        """
        if self.bus is None:
            return
        self.bus.subscribe(MessageType.BRANCH_DECISION,   self.on_branch_decision)
        self.bus.subscribe(MessageType.DEMAND_ADJUSTMENT, self.on_demand_adjustment)
        self.bus.subscribe(MessageType.POLICY_UPDATE,     self.on_policy_update)

    # ── Message handlers ──────────────────────────────────────────────────────

    def on_branch_decision(self, message) -> None:
        """
        Receive InventoryAgent branch decision and update any matching
        open order. In simulation mode orders are resolved synchronously
        so this handler primarily serves as an audit trail.
        """
        payload = message.payload
        branch  = payload.get("branch", "?")
        if branch == "C":
            # Branch C means external sourcing needed — log for diagnostics
            pass  # SupplierDiscoveryAgent handles this in the full system

    def on_demand_adjustment(self, message) -> None:
        """Receive demand surge alert — note elevated risk for new orders."""
        pass  # Routing policy adjustments handled by Q-Agent policy updates

    def on_policy_update(self, message) -> None:
        """Receive updated behaviour policies from the Q-Agent."""
        pass  # Policy updates applied at production decision level

    # ── Core order processing ─────────────────────────────────────────────────

    def process_demand(
        self,
        demand:          float,
        step:            int,
        production:      float = 0.0,
        transport:       float = 0.0,
        active_disruptions: Optional[list] = None,
    ) -> dict:
        """
        Process one demand event through the full order state machine.

        This is the main entry point called once per simulation step.
        Returns a result dict compatible with the simulation runner.

        Steps executed:
            1. Create order in RECEIVED state
            2. Transition to INVENTORY_CHECK
            3. If InventoryAgent available: use it for routing
               Otherwise: fallback to simple min(demand, transport) logic
            4. Transition to IN_TRANSIT → DELIVERED → COMPLETE
            5. Publish ORDER_FULFILLED to bus
            6. Return result dict

        Returns:
        {
            "order_id":    str,
            "satisfied":   float,
            "cost":        float,
            "delay":       float,
            "branch":      str,
            "final_state": str,
            "transfer_units": float,
        }
        """
        self._step_count += 1
        order_id = self._make_order_id(step)
        order    = Order(order_id=order_id, demand=demand, step=step)
        self.orders[order_id] = order

        # ── State: RECEIVED ───────────────────────────────────────────────────
        if self.bus:
            self.bus.publish(
                message_type = MessageType.ORDER_RECEIVED,
                sender       = self.name,
                payload      = {"order_id": order_id, "demand": demand},
                priority     = Priority.INFO,
                step         = step,
            )

        # ── State: INVENTORY_CHECK ────────────────────────────────────────────
        order.transition(OrderState.INVENTORY_CHECK, step, "Checking global inventory")
        self._publish_state_change(order, step)

        satisfied      = 0.0
        transfer_units = 0.0
        branch         = "A"

        if self.inventory_agent is not None:
            # Use InventoryAgent for full Branch A/B/C routing
            routing = self.inventory_agent.evaluate_and_route(
                demand        = demand,
                customer_zone = self.inventory_agent.customer_zone,
                step          = step,
            )
            satisfied      = routing["units_fulfilled"]
            transfer_units = routing["units_transferred"]
            branch         = routing["branch"]

            if branch == "C":
                # ── State: SOURCING (external procurement needed) ─────────────
                order.transition(
                    OrderState.SOURCING, step,
                    "All warehouses depleted — external sourcing required",
                )
                self._publish_state_change(order, step)
        else:
            # Fallback: simple transport-limited fulfilment (no InventoryAgent)
            satisfied = min(transport, demand)
            branch    = "A"

        satisfied      = min(satisfied, demand)
        delay          = max(0.0, demand - satisfied)
        cost           = production * 1.0 + delay * 5.0

        # ── State: IN_TRANSIT → DELIVERED ─────────────────────────────────────
        order.transition(
            OrderState.IN_TRANSIT, step,
            f"Branch {branch} — {satisfied:.0f}/{demand:.0f} units dispatched",
        )
        self._publish_state_change(order, step)

        order.transition(
            OrderState.DELIVERED, step,
            f"{satisfied:.0f} units delivered, {delay:.0f} units delayed",
        )
        self._publish_state_change(order, step)

        # ── Finalise order ────────────────────────────────────────────────────
        order.branch         = branch
        order.satisfied      = satisfied
        order.cost           = cost
        order.delay          = delay
        order.transfer_units = transfer_units

        fill_rate = satisfied / max(demand, 1e-9)
        if fill_rate < self.SLA_FILL_RATE:
            self.sla_breach_count += 1

        order.transition(
            OrderState.COMPLETE, step,
            f"Fill rate: {fill_rate:.3f} | SLA: {'PASS' if fill_rate >= self.SLA_FILL_RATE else 'FAIL'}",
        )
        self._publish_state_change(order, step)

        # ── Publish ORDER_FULFILLED ────────────────────────────────────────────
        if self.bus:
            self.bus.publish(
                message_type = MessageType.ORDER_FULFILLED,
                sender       = self.name,
                payload      = order.to_dict(),
                priority     = Priority.INFO,
                step         = step,
            )

        # ── Episode-level accumulation ────────────────────────────────────────
        self.total_satisfied += satisfied
        self.total_demand    += demand
        self.completed_orders.append(order)

        return {
            "order_id":       order_id,
            "satisfied":      round(satisfied,      2),
            "cost":           round(cost,            2),
            "delay":          round(delay,           2),
            "branch":         branch,
            "final_state":    order.state.value,
            "transfer_units": round(transfer_units,  2),
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_order_id(self, step: int) -> str:
        """Generate a short readable order ID."""
        uid = str(uuid.uuid4()).replace("-", "")[:8].upper()
        return f"ORD-{step:06d}-{uid}"

    def _publish_state_change(self, order: Order, step: int) -> None:
        """Publish the most recent state transition to the bus."""
        if self.bus is None or not order.history:
            return
        last = order.history[-1]
        self.bus.publish_order_state_change(
            sender    = self.name,
            order_id  = order.order_id,
            old_state = last["old_state"],
            new_state = last["new_state"],
            details   = {"branch": order.branch, "demand": order.demand},
            step      = step,
        )

    # ── Aggregates ────────────────────────────────────────────────────────────

    @property
    def episode_fill_rate(self) -> float:
        if self.total_demand == 0:
            return 1.0
        return round(self.total_satisfied / self.total_demand, 4)

    @property
    def sla_breach_rate(self) -> float:
        n = len(self.completed_orders)
        if n == 0:
            return 0.0
        return round(self.sla_breach_count / n, 4)

    def snapshot(self) -> dict:
        """Full state snapshot for dashboard and diagnostics."""
        branch_counts = {"A": 0, "B": 0, "C": 0}
        for o in self.completed_orders:
            branch_counts[o.branch] = branch_counts.get(o.branch, 0) + 1

        return {
            "total_orders":     len(self.completed_orders),
            "total_satisfied":  round(self.total_satisfied, 2),
            "total_demand":     round(self.total_demand,    2),
            "episode_fill_rate":self.episode_fill_rate,
            "sla_breach_count": self.sla_breach_count,
            "sla_breach_rate":  self.sla_breach_rate,
            "branch_counts":    branch_counts,
        }

    # ── Reset ─────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Reset all episode state for a new training episode."""
        self.orders.clear()
        self.completed_orders.clear()
        self.total_satisfied  = 0.0
        self.total_demand     = 0.0
        self.sla_breach_count = 0
        self._step_count      = 0  