"""
api/order_orchestrator.py

OrderOrchestrator — sequential MAS pipeline executor.

Coordinates all five supply-chain agents in order:
    1. OrderManagementAgent
    2. InventoryAgent
    3. ProcurementAgent   (conditional — only if inventory insufficient)
    4. LogisticsAgent
    5. LastMileDeliveryAgent

Each stage publishes A2A (agent-to-agent) SSE events so the frontend
mas-ops.html can animate in real time.

Usage:
    orchestrator = OrderOrchestrator(
        order_id="ORD-123",
        cart_items=[{"sku": "CRSC-1500", "qty": 3}],
        environment_context="Winter",
        customer_id="CUST-001",
        push_fn=_push,
    )
    result = orchestrator.execute()
"""

from __future__ import annotations

import time
import random
import datetime
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any

# ── Load .env (explicit path so it works regardless of cwd) ──────────────────
try:
    from dotenv import load_dotenv  # type: ignore
    _ENV_PATH = Path(__file__).parent.parent / ".env"
    load_dotenv(dotenv_path=_ENV_PATH, override=True)
except ImportError:
    pass  # dotenv optional — env vars may already be set

sys.path.insert(0, str(Path(__file__).parent.parent))

from communication.message_bus import MessageBus, MessageType, Priority
from warehouse.warehouse_network import WarehouseNetwork
from ucp.ucp_product_catalog import ProductCatalog

from agents.order_management_agent import OrderManagementAgent
from agents.inventory_agent import InventoryAgent
from agents.procurement_agent import ProcurementAgent
from agents.logistics_agent import LogisticsAgent
from agents.last_mile_agent import LastMileAgent

# ── Automations ────────────────────────────────────────────────────────────────
from automations.notifications import send_desktop_notification
from automations.warehouse_logger import log_warehouse_transfer
from automations.email_sender import EmailSender
from automations.telegram_alerts import TelegramAlert


_catalog = ProductCatalog()
DELAY = 0.7   # seconds between agent pipeline steps


def _now() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


class OrderOrchestrator:
    """
    Executes the full supply-chain MAS pipeline synchronously in a background thread.

    Each agent method:
      • Does real agent work
      • Fires the relevant automation (notification / CSV / email / Telegram)
      • Publishes one or more SSE events via push_fn

    Args:
        order_id:            Unique order identifier (e.g. "ORD-ABC123").
        cart_items:          List of {"sku": str, "qty": int} dicts.
        environment_context: "Winter" or "Summer" — controls inventory routing %.
        customer_id:         Customer identifier string.
        push_fn:             Callable(event_dict, order_id) to push SSE events.
    """

    def __init__(
        self,
        order_id: str,
        cart_items: List[Dict[str, Any]],
        environment_context: str,
        customer_id: str,
        push_fn: Callable,
    ) -> None:
        self.order_id = order_id
        self.cart_items = cart_items
        self.environment_context = environment_context
        self.customer_id = customer_id
        self._push = push_fn

        # Shared MAS infrastructure
        self.bus = MessageBus()
        self.network = WarehouseNetwork()

        # Compute total demand
        self.total_demand: float = max(
            sum(
                it["qty"] * (_catalog.get(it["sku"]).base_demand * 0.1
                             if _catalog.get(it["sku"]) else 10.0)
                for it in cart_items
            ),
            5.0,
        )
        # Raw cart unit count (used for invoice / email display)
        self.cart_units: int = sum(it.get("qty", 1) for it in cart_items)

        # ── Demand logging — non-blocking, never raises ───────────────────────
        try:
            from forecasting.demand_engine import log_demand_items  # type: ignore
            log_demand_items(cart_items=cart_items, order_id=order_id)
        except Exception as _dl_exc:
            print(f"[ORCHESTRATOR] demand-log skipped: {_dl_exc}")

        # Result accumulator
        self._result: Dict[str, Any] = {
            "order_id": order_id,
            "status": "PROCESSING",
            "branch": "A",
            "delivered": 0.0,
            "fill_rate": 0.0,
        }

    # ── Public entry point ────────────────────────────────────────────────────

    def execute(self) -> Dict[str, Any]:
        """
        Run the full MAS pipeline sequentially.  Blocks until complete.

        Returns:
            Result dict with keys: order_id, status, branch, delivered, fill_rate.
        """
        self._push_status("PROCESSING", "received",
                          f"Order received — {self.cart_units} items / "
                          f"{round(self.total_demand, 1)} units demanded")

        self._execute_order_management_agent()
        routing = self._execute_inventory_agent()
        branch = routing.get("branch", "A")
        self._result["branch"] = branch
        available = routing.get("units_fulfilled", self.total_demand)
        wh_inv = routing.get("wh_inv", 100.0)

        # Always send procurement notification (purchase order to supplier network)
        self._send_procurement_notification(available, wh_inv, branch)

        # Conditional procurement agent (Branch C — stock depleted)
        if branch == "C":
            available = self._execute_procurement_agent(available, wh_inv)

        transport = self._execute_logistics_agent(available)
        delivered = self._execute_last_mile_agent(transport)

        fill_rate = round(delivered / max(self.total_demand, 1e-9), 4)
        self._result.update({"status": "DELIVERED", "delivered": round(delivered, 1),
                              "fill_rate": fill_rate,
                              "cart_units": self.cart_units})

        self._push_status(
            "DELIVERED", "delivered",
            f"Delivered {round(delivered,1)}/{round(self.total_demand,1)} units — "
            f"Fill rate {fill_rate:.0%}"
        )
        self._push({"type": "all_idle", "ts": _now()}, self.order_id)
        return self._result

    # ── Stage 1: Order Management ─────────────────────────────────────────────

    def _execute_order_management_agent(self) -> None:
        """Validate the order and fire desktop notification."""
        try:
            self._activate("OrderManagementAgent")
            self._push_agent_event(
                "Customer", "OrderManagementAgent", "ORDER_RECEIVED",
                {"order_id": self.order_id, "demand": round(self.total_demand, 2),
                 "items": len(self.cart_items), "context": self.environment_context},
                stage="received",
            )
            time.sleep(DELAY)

            # ── Automation 1: Desktop Notification ────────────────────────────
            send_desktop_notification(
                title="Order Validated",
                message=(
                    f"Order {self.order_id} cleared for production. "
                    f"Context: {self.environment_context}"
                ),
            )

            self._push_agent_event(
                "OrderManagementAgent", "InventoryAgent", "STOCK_CHECK",
                {"demand": round(self.total_demand, 2),
                 "environment_context": self.environment_context},
                stage="inventory_check",
            )
        except Exception as exc:
            print(f"[ORCHESTRATOR] [ERROR] OrderManagementAgent stage failed: {exc}")

    # ── Stage 2: Inventory ────────────────────────────────────────────────────

    def _execute_inventory_agent(self) -> Dict[str, Any]:
        """Run inventory routing and log the warehouse transfer to CSV."""
        try:
            self._activate("InventoryAgent")
            time.sleep(DELAY)

            inv_agent = InventoryAgent(
                network=self.network, bus=self.bus, customer_zone="A"
            )
            inv_agent.register_subscriptions()

            routing = inv_agent.evaluate_and_route(
                demand=self.total_demand, customer_zone="A", step=1
            )
            self.bus.flush(step=1)

            branch = routing["branch"]
            available = routing["units_fulfilled"]
            wh_inv = inv_agent.primary_inventory

            # Context-aware warehouse names
            if self.environment_context == "Winter":
                from_wh, to_wh = "Warehouse B (Cold)", "Warehouse A (Primary)"
                pct = 90
            else:
                from_wh, to_wh = "Warehouse B", "Warehouse A"
                pct = 60

            # ── Automation 2: CSV Log ─────────────────────────────────────────
            log_warehouse_transfer(
                agent_name="InventoryAgent",
                from_wh=from_wh,
                to_wh=to_wh,
                units=available,
                context=self.environment_context,
                order_id=self.order_id,
            )

            self._push_agent_event(
                "InventoryAgent", "OrderManagementAgent", "INVENTORY_STATUS",
                {"warehouse_A": round(wh_inv, 1), "branch": branch,
                 "available": round(available, 1), "demand": round(self.total_demand, 1),
                 "context": self.environment_context, "routing_pct": pct},
                stage="inventory_check",
                priority="WARNING" if branch == "C" else "INFO",
            )

            self._push({
                "type": "demand_update",
                "step": 1,
                "demand": round(self.total_demand, 2),
                "satisfied": round(available, 2),
                "inventory": round(wh_inv, 2),
                "order_id": self.order_id,
                "ts": _now(),
            }, self.order_id)

            self._idle("InventoryAgent")
            return {"branch": branch, "units_fulfilled": available, "wh_inv": wh_inv}

        except Exception as exc:
            print(f"[ORCHESTRATOR] [ERROR] InventoryAgent stage failed: {exc}")
            return {"branch": "A", "units_fulfilled": self.total_demand, "wh_inv": 100.0}

    # ── Stage 3a: Procurement Email (always sent after inventory check) ─────

    def _send_procurement_notification(
        self, available: float, wh_inv: float, branch: str
    ) -> None:
        """
        Always send a procurement smart-contract / purchase order email
        to the supply chain team after every inventory routing decision.
        This informs the team of stock movements regardless of branch.
        """
        try:
            supplier_name = "Global Supply Co."
            # For Branch C, use ProcurementAgent quantity; otherwise use cart units
            if branch == "C":
                from agents.procurement_agent import ProcurementAgent as _PA
                proc = _PA()
                units_to_order = proc.process_order(
                    required=self.total_demand, inventory=wh_inv, demand=self.total_demand
                )
            else:
                units_to_order = float(self.cart_units)

            cost = units_to_order * 850.0
            delivery_days = 3 if branch == "C" else 7

            sender = EmailSender()
            sender.send_procurement_email(
                order_id=self.order_id,
                supplier_name=supplier_name,
                units=units_to_order,
                cost=cost,
                delivery_days=delivery_days,
                recipient_email="adityabhowmik68@gmail.com",
            )
        except Exception as exc:
            print(f"[ORCHESTRATOR] [ERROR] Procurement notification failed: {exc}")

    # ── Stage 3: Procurement (Branch C — conditional) ────────────────────────

    def _execute_procurement_agent(
        self, available: float, wh_inv: float
    ) -> float:
        """Trigger external procurement and send smart-contract email + PDF."""
        try:
            self._activate("ProcurementAgent")
            self._push_status("PROCESSING", "procurement",
                              "Branch C — stock depleted, activating procurement")
            self._push_agent_event(
                "OrderManagementAgent", "ProcurementAgent", "PROCUREMENT_TRIGGER",
                {"demand": round(self.total_demand, 1), "inventory": round(wh_inv, 1),
                 "context": self.environment_context},
                stage="procurement", priority="WARNING",
            )
            time.sleep(DELAY)

            proc = ProcurementAgent()
            proc_qty = proc.process_order(
                required=self.total_demand, inventory=wh_inv, demand=self.total_demand
            )

            supplier_name = "Global Supply Co."
            cost = proc_qty * 850.0
            delivery_days = 3

            self._push_agent_event(
                "ProcurementAgent", "SupplierAgent", "SUPPLIER_REQUEST",
                {"units_needed": round(proc_qty, 1), "supplier": supplier_name,
                 "estimated_cost": round(cost, 2)},
                stage="procurement", priority="WARNING",
            )
            self._idle("ProcurementAgent")
            time.sleep(DELAY)
            return proc_qty

        except Exception as exc:
            print(f"[ORCHESTRATOR] [ERROR] ProcurementAgent stage failed: {exc}")
            return available

    # ── Stage 4: Logistics ────────────────────────────────────────────────────

    def _execute_logistics_agent(self, units: float) -> float:
        """Dispatch goods and send Telegram alert + CSV dispatch log."""
        try:
            self._activate("LogisticsAgent")
            self._push_agent_event(
                "FulfillmentAgent", "LogisticsAgent", "LOGISTICS_REQUEST",
                {"confirmed": round(units, 1), "context": self.environment_context},
                stage="logistics",
            )
            time.sleep(DELAY)

            logistics = LogisticsAgent()
            transport = logistics.act(units)
            destination = "Distribution Hub — North Zone"

            # ── Automation 4: Telegram Alert ──────────────────────────────────
            tg = TelegramAlert()
            tg.send_logistics_alert(
                order_id=self.order_id,
                units=transport,
                destination=destination,
            )

            # ── Automation 2b: CSV Dispatch Log ──────────────────────────────
            log_warehouse_transfer(
                agent_name="LogisticsAgent",
                from_wh="Fulfilment Centre",
                to_wh=destination,
                units=transport,
                context=self.environment_context,
                order_id=self.order_id,
                action="Dispatch",
            )

            self._push_agent_event(
                "LogisticsAgent", "LastMileDeliveryAgent", "LAST_MILE_DISPATCH",
                {"units": round(transport, 1),
                 "route": "express" if transport < 150 else "standard",
                 "destination": destination},
                stage="last_mile",
            )
            self._idle("LogisticsAgent")
            self._activate("LastMileDeliveryAgent")
            return transport

        except Exception as exc:
            print(f"[ORCHESTRATOR] [ERROR] LogisticsAgent stage failed: {exc}")
            return units

    # ── Stage 5: Last Mile ────────────────────────────────────────────────────

    def _execute_last_mile_agent(self, transport: float) -> float:
        """Complete delivery and send fulfillment confirmation email."""
        try:
            time.sleep(DELAY)
            lm = LastMileAgent()
            result = lm.deliver(transport, step=1)
            delivered = result["delivered"]

            self._push_agent_event(
                "LastMileDeliveryAgent", "Customer", "DELIVERY_COMPLETE",
                {"delivered": round(delivered, 1), "demand": round(self.total_demand, 1),
                 "route": result.get("route", "standard"),
                 "on_time": result.get("on_time", True)},
                stage="delivered",
                priority="INFO" if delivered >= self.total_demand * 0.9 else "WARNING",
            )

            # ── Automation 5: Fulfillment Confirmation Email + Invoice PDF ─────
            sender = EmailSender()
            sender.send_fulfillment_email(
                order_id=self.order_id,
                recipient_email="adityabhowmik68@gmail.com",
                delivered_units=delivered,
                cart_units=self.cart_units,
                context=self.environment_context,
            )

            self._idle("LastMileDeliveryAgent")
            self._idle("OrderManagementAgent")
            return delivered

        except Exception as exc:
            print(f"[ORCHESTRATOR] [ERROR] LastMileAgent stage failed: {exc}")
            return transport

    # ── SSE helpers ───────────────────────────────────────────────────────────

    def _push_agent_event(
        self,
        from_agent: str,
        to_agent: str,
        msg_type: str,
        payload: dict,
        stage: str = "",
        priority: str = "INFO",
    ) -> None:
        """Build and push a standard agent_message SSE event."""
        ev = {
            "type": "agent_message",
            "from": from_agent,
            "to": to_agent,
            "msg_type": msg_type,
            "payload": payload,
            "ts": _now(),
            "order_id": self.order_id,
            "stage": stage,
            "priority": priority,
            "environment_context": self.environment_context,
        }
        self._push(ev, self.order_id)

    def _push_status(self, status: str, stage: str, detail: str = "") -> None:
        self._push({
            "type": "order_status",
            "order_id": self.order_id,
            "status": status,
            "stage": stage,
            "detail": detail,
            "ts": _now(),
        }, self.order_id)

    def _activate(self, agent: str) -> None:
        self._push({"type": "agent_status", "agent": agent,
                    "status": "ACTIVE", "ts": _now()}, self.order_id)

    def _idle(self, agent: str) -> None:
        self._push({"type": "agent_status", "agent": agent,
                    "status": "IDLE", "ts": _now()}, self.order_id)
