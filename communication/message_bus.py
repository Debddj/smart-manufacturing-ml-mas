"""
Agent-to-Agent (A2A) message bus for the decentralized supply chain MAS.

Replaces direct function calls between agents with a priority-queue
publish/subscribe system. This is the infrastructure that allows the
DisruptionEngine to alert the InventoryAgent and LogisticsAgent
simultaneously without the simulation runner coordinating it.

Architecture:
    - Agents subscribe to message types they care about at startup
    - Agents publish events when state changes occur
    - flush() delivers all queued messages in priority order (ALERT first)
    - All messages are archived in message_log for dashboard replay

Message flow (matching the architecture diagram):
    DisruptionEngine    → STOCK_RISK, ROUTE_CHANGE, SUPPLIER_SWITCH, DEMAND_ADJUSTMENT
    DemandForecasting   → DEMAND_FORECAST (purple lines)
    InventoryAgent      → INVENTORY_STATUS, BRANCH_DECISION
    OrderManagement     → ORDER_RECEIVED, ORDER_STATE_CHANGE, ORDER_FULFILLED
    SupplierDiscovery   → SUPPLIER_SELECTED, SUPPLIER_BID
    Q-Agent             → POLICY_UPDATE (blue dashed lines)
    LogisticsAgent      → TRANSIT_STATUS, DELIVERY_COMPLETE

Usage:
    bus = MessageBus()

    # Subscribe
    bus.subscribe(MessageType.STOCK_RISK, inventory_agent.on_stock_risk)
    bus.subscribe(MessageType.POLICY_UPDATE, logistics_agent.on_policy_update)

    # Publish
    bus.publish(
        message_type = MessageType.STOCK_RISK,
        sender       = "DisruptionEngine",
        payload      = {"warehouse": "A", "risk_level": "high"},
        priority     = Priority.ALERT,
    )

    # Deliver all queued messages once per simulation step
    bus.flush(step=day)
"""

from __future__ import annotations

import heapq
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Dict, List, Optional


# ── Priority levels ────────────────────────────────────────────────────────────

class Priority(IntEnum):
    ALERT   = 0   # highest — disruptions, SLA breaches, critical inventory
    WARNING = 1   # approaching thresholds, non-critical issues
    INFO    = 2   # routine status updates
    ACTION  = 3   # lowest — normal operational decisions


# ── Message types ──────────────────────────────────────────────────────────────

class MessageType:
    """
    All A2A message type string constants.
    Using a class of string constants (rather than an Enum) makes it easy
    to add new types without breaking existing subscribers.
    """
    # From DisruptionEngine (pink lines in diagram)
    STOCK_RISK        = "stock_risk"
    ROUTE_CHANGE      = "route_change"
    SUPPLIER_SWITCH   = "supplier_switch"
    DEMAND_ADJUSTMENT = "demand_adjustment"

    # From InventoryAgent
    INVENTORY_STATUS  = "inventory_status"
    BRANCH_DECISION   = "branch_decision"
    TRANSFER_REQUEST  = "transfer_request"

    # From OrderManagementAgent
    ORDER_RECEIVED    = "order_received"
    ORDER_STATE_CHANGE= "order_state_change"
    ORDER_FULFILLED   = "order_fulfilled"

    # From SupplierDiscoveryAgent
    SUPPLIER_SELECTED = "supplier_selected"
    SUPPLIER_BID      = "supplier_bid"

    # From Q-Agent / PolicyBroadcaster (blue dashed lines)
    POLICY_UPDATE     = "policy_update"

    # From DemandForecastingAgent (purple lines)
    DEMAND_FORECAST   = "demand_forecast"

    # From LogisticsAgent
    TRANSIT_STATUS    = "transit_status"
    DELIVERY_COMPLETE = "delivery_complete"

    # System-level
    SYSTEM_CHECKPOINT = "system_checkpoint"
    SLA_BREACH        = "sla_breach"
    SLA_RESTORED      = "sla_restored"


# ── Message dataclass ──────────────────────────────────────────────────────────

@dataclass(order=True)
class Message:
    """
    A single A2A message.

    Fields are ordered so heapq sorts by (priority, seq) only.
    Non-comparable fields (type, sender, payload) come after seq
    and are excluded from comparison via compare=False.

    priority  : int from Priority enum — lower number = higher priority
    seq       : monotonic counter — guarantees FIFO within same priority
    type      : MessageType constant string
    sender    : agent name string for logging and debugging
    payload   : arbitrary dict — subscribers unpack what they need
    timestamp : wall-clock time of publication
    step      : simulation step number at time of publication
    """
    priority : int  = field(compare=True)
    seq      : int  = field(compare=True,  default=0)
    type     : str  = field(compare=False, default="")
    sender   : str  = field(compare=False, default="")
    payload  : dict = field(compare=False, default_factory=dict)
    timestamp: float= field(compare=False, default_factory=time.time)
    step     : int  = field(compare=False, default=0)

    def __post_init__(self):
        if isinstance(self.priority, Priority):
            self.priority = int(self.priority)


# ── Message bus ────────────────────────────────────────────────────────────────

class MessageBus:
    """
    Synchronous priority-queue message bus.

    Lifecycle per simulation episode:
        1. Agents register subscriptions once at startup (subscribe)
        2. Each step: agents publish events (publish)
        3. End of step: call flush(step) to deliver all queued messages
           in priority order — ALERT messages always delivered before INFO
        4. Delivered messages archived in message_log (capped at max_log_size)
        5. At episode end: call reset() to clear queue and log

    Thread-safety: not thread-safe — designed for single-threaded simulation.

    Error isolation: if a subscriber handler raises an exception, the bus
    catches it, logs a warning, and continues delivering remaining messages.
    One broken handler never blocks others.
    """

    def __init__(self, max_log_size: int = 5_000):
        # {message_type: [handler, ...]}
        self._subscriptions: Dict[str, List[Callable]] = defaultdict(list)
        # heapq — Messages sorted by (priority, seq)
        self._queue: List[Message] = []
        # Monotonic counter for stable ordering within same priority
        self._seq: int = 0
        # Current simulation step
        self._step: int = 0
        # Archived delivered messages
        self.message_log: List[Message] = []
        self._max_log_size = max_log_size
        # Per-type publish counts for diagnostics
        self._stats: Dict[str, int] = defaultdict(int)
        # Count of handler errors (non-fatal)
        self._handler_errors: int = 0

    # ── Subscription management ────────────────────────────────────────────────

    def subscribe(self, message_type: str, handler: Callable) -> None:
        """
        Register handler to receive messages of message_type.
        handler signature: handler(message: Message) -> None
        Duplicate subscriptions are silently ignored.
        """
        if handler not in self._subscriptions[message_type]:
            self._subscriptions[message_type].append(handler)

    def unsubscribe(self, message_type: str, handler: Callable) -> None:
        """Remove a previously registered handler."""
        handlers = self._subscriptions.get(message_type, [])
        if handler in handlers:
            handlers.remove(handler)

    def subscriber_count(self, message_type: str) -> int:
        """Return number of handlers registered for a message type."""
        return len(self._subscriptions.get(message_type, []))

    # ── Publication ────────────────────────────────────────────────────────────

    def publish(
        self,
        message_type: str,
        sender:       str,
        payload:      dict,
        priority:     int = Priority.INFO,
        step:         Optional[int] = None,
    ) -> Message:
        """
        Queue a message for delivery at next flush().

        Returns the Message object for reference (e.g. logging).
        Does not deliver immediately — call flush() to deliver.
        """
        self._seq += 1
        msg = Message(
            priority  = int(priority),
            seq       = self._seq,
            type      = message_type,
            sender    = sender,
            payload   = payload,
            timestamp = time.time(),
            step      = step if step is not None else self._step,
        )
        heapq.heappush(self._queue, msg)
        self._stats[message_type] += 1
        return msg

    # ── Delivery ───────────────────────────────────────────────────────────────

    def flush(self, step: Optional[int] = None) -> int:
        """
        Deliver all queued messages in priority order.

        Call once per simulation step after all agents have published.
        Returns the number of messages delivered this flush.

        Handler exceptions are caught and counted — delivery continues.
        """
        if step is not None:
            self._step = step

        delivered = 0
        while self._queue:
            msg = heapq.heappop(self._queue)
            handlers = self._subscriptions.get(msg.type, [])
            for handler in handlers:
                try:
                    handler(msg)
                except Exception as exc:
                    self._handler_errors += 1
                    print(f"[MessageBus] Handler error — type={msg.type} "
                          f"sender={msg.sender} handler={handler.__name__}: {exc}")

            # Archive delivered message
            self.message_log.append(msg)
            if len(self.message_log) > self._max_log_size:
                self.message_log.pop(0)
            delivered += 1

        return delivered

    # ── Convenience publishers matching the architecture diagram ──────────────

    def publish_disruption_alert(
        self,
        sender:          str,
        disruption_type: str,
        affected_agents: list,
        step:            Optional[int] = None,
    ) -> Message:
        """
        Pink dashed lines from DisruptionEngine in the architecture diagram.
        Routes to the semantically correct MessageType per disruption type.
        """
        type_map = {
            "supplier_failure":    MessageType.SUPPLIER_SWITCH,
            "logistics_breakdown": MessageType.ROUTE_CHANGE,
            "demand_surge":        MessageType.DEMAND_ADJUSTMENT,
            "factory_slowdown":    MessageType.STOCK_RISK,
        }
        msg_type = type_map.get(disruption_type, MessageType.STOCK_RISK)
        return self.publish(
            message_type = msg_type,
            sender       = sender,
            payload      = {
                "disruption_type":  disruption_type,
                "affected_agents":  affected_agents,
                "action_required":  True,
            },
            priority = Priority.ALERT,
            step     = step,
        )

    def publish_policy_update(
        self,
        sender: str,
        policy: dict,
        step:   Optional[int] = None,
    ) -> Message:
        """
        Blue dashed lines — Q-Agent pushing updated behaviour policies
        to operational agents after learning from episode results.
        """
        return self.publish(
            message_type = MessageType.POLICY_UPDATE,
            sender       = sender,
            payload      = policy,
            priority     = Priority.INFO,
            step         = step,
        )

    def publish_demand_forecast(
        self,
        sender:   str,
        forecast: float,
        horizon:  int = 1,
        step:     Optional[int] = None,
    ) -> Message:
        """
        Purple lines — DemandForecastingAgent broadcasting predictions
        to InventoryAgent and OrderManagementAgent.
        """
        return self.publish(
            message_type = MessageType.DEMAND_FORECAST,
            sender       = sender,
            payload      = {"forecast": forecast, "horizon_steps": horizon},
            priority     = Priority.INFO,
            step         = step,
        )

    def publish_branch_decision(
        self,
        sender:   str,
        branch:   str,
        decision: dict,
        step:     Optional[int] = None,
    ) -> Message:
        """
        InventoryAgent announcing its Branch A / B / C routing decision.
        Branch C is elevated to WARNING because it signals stock depletion.
        """
        return self.publish(
            message_type = MessageType.BRANCH_DECISION,
            sender       = sender,
            payload      = {"branch": branch, **decision},
            priority     = Priority.WARNING if branch == "C" else Priority.INFO,
            step         = step,
        )

    def publish_inventory_status(
        self,
        sender:    str,
        node_id:   str,
        inventory: float,
        capacity:  float,
        step:      Optional[int] = None,
    ) -> Message:
        """InventoryAgent reporting current stock level for a warehouse node."""
        fill_ratio = inventory / capacity if capacity > 0 else 0.0
        return self.publish(
            message_type = MessageType.INVENTORY_STATUS,
            sender       = sender,
            payload      = {
                "node_id":    node_id,
                "inventory":  round(inventory, 2),
                "capacity":   capacity,
                "fill_ratio": round(fill_ratio, 3),
                "below_safety": inventory < 20,
            },
            priority = Priority.WARNING if inventory < 20 else Priority.INFO,
            step     = step,
        )

    def publish_order_state_change(
        self,
        sender:    str,
        order_id:  str,
        old_state: str,
        new_state: str,
        details:   Optional[dict] = None,
        step:      Optional[int] = None,
    ) -> Message:
        """OrderManagementAgent announcing an order progressed through the lifecycle."""
        return self.publish(
            message_type = MessageType.ORDER_STATE_CHANGE,
            sender       = sender,
            payload      = {
                "order_id":  order_id,
                "old_state": old_state,
                "new_state": new_state,
                "details":   details or {},
            },
            priority = Priority.INFO,
            step     = step,
        )

    # ── Introspection ──────────────────────────────────────────────────────────

    def pending_count(self) -> int:
        """Number of messages queued but not yet delivered."""
        return len(self._queue)

    def stats(self) -> dict:
        """Return publishing statistics for diagnostics and dashboard."""
        return {
            "queued_messages": len(self._queue),
            "total_published": sum(self._stats.values()),
            "by_type":         dict(self._stats),
            "log_size":        len(self.message_log),
            "handler_errors":  self._handler_errors,
            "subscribers":     {
                t: len(h)
                for t, h in self._subscriptions.items()
                if h
            },
        }

    def get_recent_log(self, n: int = 50) -> List[dict]:
        """Return last n delivered messages as plain dicts for the dashboard."""
        recent = self.message_log[-n:]
        return [
            {
                "step":     m.step,
                "type":     m.type,
                "sender":   m.sender,
                "priority": m.priority,
                "payload":  m.payload,
            }
            for m in recent
        ]

    # ── Reset ──────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """
        Clear queue and log for a new training episode.
        Subscriptions are preserved — agents re-subscribe once at startup,
        not once per episode.
        """
        self._queue = []
        self._seq   = 0
        self._step  = 0
        self.message_log.clear()
        self._stats.clear()
        self._handler_errors = 0 