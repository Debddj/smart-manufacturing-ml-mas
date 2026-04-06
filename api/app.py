"""
FastAPI backend — Real-time Supply Chain MAS
Streams live agent events via SSE to both frontends.
"""
from __future__ import annotations

import asyncio
import json
import queue
import random
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# ── Project imports ────────────────────────────────────────────────────────────
import sys, os
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.order_management_agent   import OrderManagementAgent
from agents.inventory_agent          import InventoryAgent
from agents.procurement_agent        import ProcurementAgent
from agents.fulfillment_agent        import FulfillmentAgent
from agents.last_mile_agent          import LastMileAgent
from agents.logistics_agent          import LogisticsAgent
from agents.supplier_agent           import SupplierAgent
from agents.warehouse_agent          import WarehouseAgent
from communication.message_bus       import MessageBus, MessageType, Priority
from ucp.ucp_product_catalog         import ProductCatalog
from warehouse.warehouse_network     import WarehouseNetwork

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Supply Chain MAS API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent.parent

# ── Global state ──────────────────────────────────────────────────────────────
catalog      = ProductCatalog()
orders_db: Dict[str, dict] = {}          # order_id → order state
demand_history: List[dict] = []          # [{step, demand, satisfied, inventory}]
agent_states: Dict[str, dict] = {        # live agent status cards
    "OrderManagementAgent":    {"status": "IDLE", "msgs": 0, "last": ""},
    "InventoryAgent":          {"status": "IDLE", "msgs": 0, "last": ""},
    "ProcurementAgent":        {"status": "IDLE", "msgs": 0, "last": ""},
    "SupplierAgent":           {"status": "IDLE", "msgs": 0, "last": ""},
    "WarehouseAgent":          {"status": "IDLE", "msgs": 0, "last": ""},
    "FulfillmentAgent":        {"status": "IDLE", "msgs": 0, "last": ""},
    "LogisticsAgent":          {"status": "IDLE", "msgs": 0, "last": ""},
    "LastMileDeliveryAgent":   {"status": "IDLE", "msgs": 0, "last": ""},
}

# Per-order SSE queues  {order_id: [queue, …]}
_order_listeners: Dict[str, List[queue.Queue]] = defaultdict(list)
# Global broadcast queue (for MAS dashboard)
_global_listeners: List[queue.Queue] = []
_global_lock = threading.Lock()

step_counter = 0   # simulated time step


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _push(event_dict: dict, order_id: Optional[str] = None) -> None:
    """Push an SSE event to all listeners (global + per-order)."""
    payload = json.dumps(event_dict)
    with _global_lock:
        dead = []
        for q in _global_listeners:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for d in dead:
            _global_listeners.remove(d)

    if order_id and order_id in _order_listeners:
        dead = []
        for q in _order_listeners[order_id]:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for d in dead:
            _order_listeners[order_id].remove(d)


def _agent_event(
    from_agent: str,
    to_agent: str,
    msg_type: str,
    payload: dict,
    order_id: str = "",
    stage: str = "",
    priority: str = "INFO",
) -> dict:
    """Build a standard SSE event dict."""
    now_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    ev = {
        "type":     "agent_message",
        "from":     from_agent,
        "to":       to_agent,
        "msg_type": msg_type,
        "payload":  payload,
        "ts":       now_str,
        "order_id": order_id,
        "stage":    stage,
        "priority": priority,
    }
    # Update agent status cards
    for a in [from_agent, to_agent]:
        if a in agent_states:
            agent_states[a]["msgs"] += 1
            agent_states[a]["last"] = now_str
    agent_states.get(from_agent, {}).update({"status": "ACTIVE"})
    agent_states.get(to_agent,   {}).update({"status": "BUSY"})
    return ev


def _demand_event(step: int, demand: float, satisfied: float,
                  inventory: float, order_id: str = "") -> dict:
    """Build a demand-curve data event."""
    return {
        "type":      "demand_update",
        "step":      step,
        "demand":    round(demand, 2),
        "satisfied": round(satisfied, 2),
        "inventory": round(inventory, 2),
        "order_id":  order_id,
        "ts":        datetime.now().strftime("%H:%M:%S.%f")[:-3],
    }


def _status_event(order_id: str, status: str, stage: str, detail: str = "") -> dict:
    return {
        "type":     "order_status",
        "order_id": order_id,
        "status":   status,
        "stage":    stage,
        "detail":   detail,
        "ts":       datetime.now().strftime("%H:%M:%S.%f")[:-3],
    }


# ── Real agent orchestration ──────────────────────────────────────────────────

def _run_order(order_id: str, items: List[dict]) -> None:
    """
    Run a real order through the MAS pipeline in a background thread.
    Emits SSE events at each step so the dashboard animates in real-time.
    """
    global step_counter
    step_counter += 1
    step = step_counter

    # Compute total demand from cart items
    total_demand = sum(it["qty"] * catalog.get(it["sku"]).base_demand * 0.1
                       for it in items
                       if catalog.get(it["sku"]))
    total_demand = max(total_demand, 5.0)

    DELAY = 0.6   # seconds between agent steps for dramatic effect

    def sleep():
        time.sleep(DELAY)

    def activate(name: str):
        if name in agent_states:
            agent_states[name]["status"] = "ACTIVE"
        _push({"type": "agent_status", "agent": name,
                "status": "ACTIVE", "ts": datetime.now().strftime("%H:%M:%S.%f")[:-3]},
               order_id)

    def idle(name: str):
        if name in agent_states:
            agent_states[name]["status"] = "IDLE"
        _push({"type": "agent_status", "agent": name,
                "status": "IDLE", "ts": datetime.now().strftime("%H:%M:%S.%f")[:-3]},
               order_id)

    # ── Step 0: ORDER RECEIVED ─────────────────────────────────────────────────
    activate("OrderManagementAgent")
    ev = _agent_event(
        "Customer", "OrderManagementAgent", "ORDER_RECEIVED",
        {"order_id": order_id, "demand": round(total_demand, 2),
         "items": len(items)},
        order_id=order_id, stage="received", priority="INFO",
    )
    _push(ev, order_id)
    _push(_status_event(order_id, "PROCESSING", "received",
                        f"Order received — {round(total_demand,1)} units demanded"), order_id)
    sleep()

    # ── Step 1: INVENTORY CHECK ────────────────────────────────────────────────
    activate("InventoryAgent")
    ev = _agent_event(
        "OrderManagementAgent", "InventoryAgent", "STOCK_CHECK",
        {"demand": round(total_demand, 2), "step": step},
        order_id=order_id, stage="inventory_check", priority="INFO",
    )
    _push(ev, order_id)
    sleep()

    # Build a real WarehouseNetwork + InventoryAgent
    network       = WarehouseNetwork()
    bus           = MessageBus()
    inv_agent     = InventoryAgent(network=network, bus=bus, customer_zone="A")
    inv_agent.register_subscriptions()

    # Add some demand history to lower inventory realistically
    for item in items:
        p = catalog.get(item["sku"])
        if p:
            p.current_inventory = max(0, p.current_inventory - item["qty"] * 2)

    routing = inv_agent.evaluate_and_route(demand=total_demand,
                                            customer_zone="A", step=step)
    bus.flush(step=step)

    branch     = routing["branch"]
    wh_inv     = inv_agent.primary_inventory
    available  = routing["units_fulfilled"]

    # Publish warehouse state
    ev = _agent_event(
        "InventoryAgent", "OrderManagementAgent", "INVENTORY_STATUS",
        {"warehouse_A": round(wh_inv, 1), "branch": branch,
         "available": round(available, 1), "demand": round(total_demand, 1)},
        order_id=order_id, stage="inventory_check",
        priority="WARNING" if branch == "C" else "INFO",
    )
    _push(ev, order_id)
    _push(_demand_event(step, total_demand, available, wh_inv, order_id), order_id)
    demand_history.append({
        "step": step, "demand": total_demand, "satisfied": available, "inventory": wh_inv
    })
    sleep()

    # ── Step 2: Branch A — stock available ────────────────────────────────────
    if branch == "A":
        idle("InventoryAgent")
        _push(_status_event(order_id, "PROCESSING", "fulfillment",
                             f"Branch A — stock available ({round(available,1)} units)"), order_id)

        activate("FulfillmentAgent")
        ev = _agent_event(
            "OrderManagementAgent", "FulfillmentAgent", "FULFILLMENT_REQUEST",
            {"units": round(available, 1), "demand": round(total_demand, 1)},
            order_id=order_id, stage="fulfillment", priority="INFO",
        )
        _push(ev, order_id)
        sleep()

        fulfill_agent = FulfillmentAgent()
        confirmed = fulfill_agent.fulfill(available, total_demand, wh_inv)

        ev = _agent_event(
            "FulfillmentAgent", "LogisticsAgent", "LOGISTICS_REQUEST",
            {"confirmed": round(confirmed, 1), "route": "standard"},
            order_id=order_id, stage="logistics", priority="INFO",
        )
        _push(ev, order_id)
        idle("FulfillmentAgent")
        activate("LogisticsAgent")
        sleep()

        logistics = LogisticsAgent()
        transport  = logistics.act(confirmed)

        ev = _agent_event(
            "LogisticsAgent", "LastMileDeliveryAgent", "LAST_MILE_DISPATCH",
            {"units": round(transport, 1), "route": "express" if transport < 150 else "standard"},
            order_id=order_id, stage="last_mile", priority="INFO",
        )
        _push(ev, order_id)
        idle("LogisticsAgent")
        activate("LastMileDeliveryAgent")
        sleep()

        lm    = LastMileAgent()
        result = lm.deliver(transport, step=step)
        delivered = result["delivered"]

        idle("LastMileDeliveryAgent")
        idle("OrderManagementAgent")

    # ── Step 2b: Branch B — inter-warehouse transfer ──────────────────────────
    elif branch == "B":
        transfer = routing.get("units_transferred", 0)
        idle("InventoryAgent")
        _push(_status_event(order_id, "PROCESSING", "warehouse_transfer",
                             f"Branch B — inter-warehouse transfer ({round(transfer,1)} units)"), order_id)

        activate("WarehouseAgent")
        ev = _agent_event(
            "InventoryAgent", "WarehouseAgent", "TRANSFER_REQUEST",
            {"from": "B", "to": "A", "units": round(transfer, 1)},
            order_id=order_id, stage="warehouse_transfer", priority="WARNING",
        )
        _push(ev, order_id)
        sleep()
        idle("WarehouseAgent")

        activate("FulfillmentAgent")
        ev = _agent_event(
            "OrderManagementAgent", "FulfillmentAgent", "FULFILLMENT_REQUEST",
            {"units": round(available, 1), "demand": round(total_demand, 1)},
            order_id=order_id, stage="fulfillment", priority="INFO",
        )
        _push(ev, order_id)
        sleep()

        fulfill_agent = FulfillmentAgent()
        confirmed = fulfill_agent.fulfill(available, total_demand, wh_inv)

        ev = _agent_event(
            "FulfillmentAgent", "LogisticsAgent", "LOGISTICS_REQUEST",
            {"confirmed": round(confirmed, 1)},
            order_id=order_id, stage="logistics", priority="INFO",
        )
        _push(ev, order_id)
        idle("FulfillmentAgent")
        activate("LogisticsAgent")
        sleep()

        logistics  = LogisticsAgent()
        transport  = logistics.act(confirmed)
        lm         = LastMileAgent()
        result     = lm.deliver(transport, step=step)
        delivered  = result["delivered"]

        idle("LogisticsAgent")
        activate("LastMileDeliveryAgent")
        sleep()
        idle("LastMileDeliveryAgent")
        idle("OrderManagementAgent")

    # ── Step 2c: Branch C — external procurement ──────────────────────────────
    else:
        idle("InventoryAgent")
        _push(_status_event(order_id, "PROCESSING", "procurement",
                             "Branch C — stock depleted, activating procurement"), order_id)

        activate("ProcurementAgent")
        ev = _agent_event(
            "OrderManagementAgent", "ProcurementAgent", "PROCUREMENT_TRIGGER",
            {"demand": round(total_demand, 1), "inventory": round(wh_inv, 1)},
            order_id=order_id, stage="procurement", priority="WARNING",
        )
        _push(ev, order_id)
        sleep()

        proc = ProcurementAgent()
        proc_qty = proc.process_order(
            required=total_demand,
            inventory=wh_inv,
            demand=total_demand,
        )

        activate("SupplierAgent")
        ev = _agent_event(
            "ProcurementAgent", "SupplierAgent", "SUPPLIER_REQUEST",
            {"units_needed": round(proc_qty, 1)},
            order_id=order_id, stage="procurement", priority="WARNING",
        )
        _push(ev, order_id)
        sleep()

        supplier = SupplierAgent()
        supply   = supplier.act()

        ev = _agent_event(
            "SupplierAgent", "WarehouseAgent", "RESTOCK_DELIVERY",
            {"units": supply, "lead_time": "1 step"},
            order_id=order_id, stage="restock", priority="INFO",
        )
        _push(ev, order_id)
        idle("SupplierAgent")
        activate("WarehouseAgent")
        sleep()

        inv_agent.receive_production("A", supply)
        new_inv = inv_agent.primary_inventory
        _push(_demand_event(step + 0.5, total_demand, min(supply, total_demand),
                             new_inv, order_id), order_id)
        demand_history.append({
            "step": step + 0.5, "demand": total_demand,
            "satisfied": min(supply, total_demand), "inventory": new_inv
        })

        idle("WarehouseAgent")
        activate("FulfillmentAgent")
        ev = _agent_event(
            "WarehouseAgent", "FulfillmentAgent", "FULFILLMENT_REQUEST",
            {"units": round(min(supply, total_demand), 1)},
            order_id=order_id, stage="fulfillment", priority="INFO",
        )
        _push(ev, order_id)
        sleep()

        fulfill_agent = FulfillmentAgent()
        confirmed = fulfill_agent.fulfill(min(supply, total_demand), total_demand, new_inv)

        activate("LogisticsAgent")
        ev = _agent_event(
            "FulfillmentAgent", "LogisticsAgent", "LOGISTICS_REQUEST",
            {"confirmed": round(confirmed, 1)},
            order_id=order_id, stage="logistics", priority="INFO",
        )
        _push(ev, order_id)
        idle("FulfillmentAgent")
        sleep()

        logistics = LogisticsAgent()
        transport  = logistics.act(confirmed)
        lm         = LastMileAgent()
        result     = lm.deliver(transport, step=step)
        delivered  = result["delivered"]

        activate("LastMileDeliveryAgent")
        sleep()
        idle("LastMileDeliveryAgent")
        idle("OrderManagementAgent")
        idle("ProcurementAgent")

    # ── Final: DELIVERED ───────────────────────────────────────────────────────
    fill_rate = round(delivered / max(total_demand, 1e-9), 4)
    ev = _agent_event(
        "LastMileDeliveryAgent", "Customer", "DELIVERY_COMPLETE",
        {"delivered": round(delivered, 1), "demand": round(total_demand, 1),
         "fill_rate": fill_rate, "route": result.get("route", "standard"),
         "on_time": result.get("on_time", True)},
        order_id=order_id, stage="delivered",
        priority="INFO" if fill_rate >= 0.9 else "WARNING",
    )
    _push(ev, order_id)
    _push(_status_event(order_id, "DELIVERED", "delivered",
                        f"Delivered {round(delivered,1)}/{round(total_demand,1)} units — "
                        f"Fill rate {fill_rate:.0%}"), order_id)

    orders_db[order_id].update({
        "status":    "DELIVERED",
        "delivered": round(delivered, 1),
        "fill_rate": fill_rate,
        "branch":    branch,
        "completed": datetime.now().isoformat(),
    })

    # Reset all agents to idle
    for name in agent_states:
        agent_states[name]["status"] = "IDLE"
    _push({"type": "all_idle", "ts": datetime.now().isoformat()}, order_id)


# ── API routes ─────────────────────────────────────────────────────────────────

@app.get("/api/products")
def get_products():
    return [p.to_ucp_listing() for p in catalog.all()]


@app.post("/api/order")
async def place_order(request: Request):
    body = await request.json()
    items      = body.get("items", [])   # [{sku, qty}]
    order_id   = "ORD-" + uuid.uuid4().hex[:8].upper()

    orders_db[order_id] = {
        "order_id": order_id,
        "items":    items,
        "status":   "PROCESSING",
        "created":  datetime.now().isoformat(),
    }

    # Run MAS pipeline in background thread
    t = threading.Thread(target=_run_order, args=(order_id, items), daemon=True)
    t.start()

    return {"order_id": order_id, "status": "PROCESSING"}


@app.get("/api/orders/{order_id}")
def get_order(order_id: str):
    return orders_db.get(order_id, {"error": "not found"})


@app.get("/api/agents")
def get_agents():
    return agent_states


@app.get("/api/demand-history")
def get_demand_history():
    return demand_history[-50:]   # last 50 data points


@app.get("/api/inventory")
def get_inventory():
    result = {}
    for p in catalog.all():
        result[p.sku] = {
            "name": p.name,
            "inventory": p.current_inventory,
            "status": catalog.get_inventory(p.sku)["status"],
        }
    return result


@app.get("/api/stream/{order_id}")
async def stream_order(order_id: str, request: Request):
    """SSE stream for a specific order."""
    q: queue.Queue = queue.Queue(maxsize=200)
    _order_listeners[order_id].append(q)

    async def event_generator():
        yield f"data: {json.dumps({'type': 'connected', 'order_id': order_id})}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = q.get_nowait()
                    yield f"data: {msg}\n\n"
                except queue.Empty:
                    await asyncio.sleep(0.05)
        finally:
            if order_id in _order_listeners:
                try:
                    _order_listeners[order_id].remove(q)
                except ValueError:
                    pass

    return StreamingResponse(event_generator(),
                              media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache",
                                       "X-Accel-Buffering": "no"})


@app.get("/api/stream")
async def stream_global(request: Request):
    """SSE stream for the MAS dashboard (all events)."""
    q: queue.Queue = queue.Queue(maxsize=500)
    with _global_lock:
        _global_listeners.append(q)

    async def event_generator():
        yield f"data: {json.dumps({'type': 'connected', 'channel': 'global'})}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = q.get_nowait()
                    yield f"data: {msg}\n\n"
                except queue.Empty:
                    await asyncio.sleep(0.05)
        finally:
            with _global_lock:
                try:
                    _global_listeners.remove(q)
                except ValueError:
                    pass

    return StreamingResponse(event_generator(),
                              media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache",
                                       "X-Accel-Buffering": "no"})


# ── Static HTML pages ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_shop():
    p = BASE_DIR / "frontend" / "shop.html"
    return p.read_text(encoding="utf-8")


@app.get("/shop", response_class=HTMLResponse)
async def serve_shop_alias():
    p = BASE_DIR / "frontend" / "shop.html"
    return p.read_text(encoding="utf-8")


@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():
    p = BASE_DIR / "frontend" / "mas-ops.html"
    return p.read_text(encoding="utf-8")


@app.get("/mas-ops", response_class=HTMLResponse)
async def serve_mas_ops():
    p = BASE_DIR / "frontend" / "mas-ops.html"
    return p.read_text(encoding="utf-8")
