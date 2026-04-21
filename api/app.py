"""
FastAPI backend — Real-time Supply Chain MAS
Streams live agent events via SSE to both frontends.
"""
from __future__ import annotations

import asyncio
import csv
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

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── Load .env ──────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except ImportError:
    pass

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
from forecasting.demand_engine       import load_demand_data, aggregate_demand, predict_demand

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

    # ── Demand logging ────────────────────────────────────────────────────────
    # Append each ordered item (name + qty) with a timestamp to demand_log.csv.
    # Creates the file with a header row if it does not already exist.
    _demand_log_path = BASE_DIR / "demand_log.csv"
    try:
        _write_header = not _demand_log_path.exists()
        with open(_demand_log_path, mode="a", newline="", encoding="utf-8") as _f:
            _writer = csv.writer(_f)
            if _write_header:
                _writer.writerow(["timestamp", "item_name", "quantity"])
            _log_ts = datetime.now().isoformat()
            for _it in items:
                _product = catalog.get(_it["sku"])
                _item_name = _product.name if _product else _it["sku"]
                _writer.writerow([_log_ts, _item_name, _it["qty"]])
    except Exception as _exc:  # never crash the pipeline over logging
        pass
    # ─────────────────────────────────────────────────────────────────────────

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


# ── Phase 3.1 — NEW v1 trigger_order endpoint ────────────────────────────────

@app.post("/api/v1/trigger_order")
async def trigger_order_v1(request: Request):
    """
    POST /api/v1/trigger_order

    Body: {cart_items: [{sku, qty}], environment_context: str, customer_id: str}
    Returns: {status, order_id, message}

    Instantiates OrderOrchestrator and runs the full MAS pipeline in a
    background thread. The frontend can then listen on SSE or WebSocket
    for real-time agent events.
    """
    from api.order_orchestrator import OrderOrchestrator  # local import to avoid circular
    body               = await request.json()
    cart_items         = body.get("cart_items", body.get("items", []))
    environment_context= body.get("environment_context", "Summer")
    customer_id        = body.get("customer_id", "CUST-ANON")

    order_id = "ORD-" + uuid.uuid4().hex[:8].upper()
    orders_db[order_id] = {
        "order_id":   order_id,
        "items":      cart_items,
        "status":     "PROCESSING",
        "created":    datetime.now().isoformat(),
        "context":    environment_context,
        "customer_id":customer_id,
    }

    def _run_orchestrator():
        orchestrator = OrderOrchestrator(
            order_id=order_id,
            cart_items=cart_items,
            environment_context=environment_context,
            customer_id=customer_id,
            push_fn=_push,
        )
        result = orchestrator.execute()
        orders_db[order_id].update(result)

    t = threading.Thread(target=_run_orchestrator, daemon=True)
    t.start()

    return JSONResponse({
        "status":   "PROCESSING",
        "order_id": order_id,
        "message":  f"Order {order_id} accepted — MAS pipeline started.",
    })


# ── Phase 3.5 — Seasonal warehouse transfer endpoint ─────────────────────────

@app.post("/api/v1/seasonal_transfer")
async def seasonal_transfer(request: Request):
    """
    POST /api/v1/seasonal_transfer

    Body: {warehouse_context: "A" | "B", date: "YYYY-MM-DD"}

    Determines the season for each warehouse based on date:
        Warehouse A: Summer = Jan–Jul (1–7), Winter = Aug–Dec (8–12)
        Warehouse B: Summer = Aug–Dec (8–12), Winter = Jan–Jul (1–7)

    If the selected warehouse context needs stock for its season, it
    automatically receives a transfer from the other warehouse and logs
    it to warehouse_log.csv.
    """
    from automations.warehouse_logger import log_warehouse_transfer
    import datetime as dt_module

    body = await request.json()
    wh_context = body.get("warehouse_context", "A")   # "A" or "B"
    date_str   = body.get("date", "")

    # Parse date
    try:
        target_date = dt_module.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return JSONResponse({"error": f"Invalid date format: {date_str}. Use YYYY-MM-DD."}, status_code=400)

    month = target_date.month

    # Determine season for each warehouse
    # Wh A: Summer = months 1–7 (Jan–Jul), Winter = months 8–12 (Aug–Dec)
    # Wh B: Summer = months 8–12 (Aug–Dec), Winter = months 1–7 (Jan–Jul)
    def get_season_A(m: int) -> str:
        return "Summer" if 1 <= m <= 7 else "Winter"

    def get_season_B(m: int) -> str:
        return "Summer" if 8 <= m <= 12 else "Winter"

    season_A = get_season_A(month)
    season_B = get_season_B(month)

    order_id = "SEA-" + uuid.uuid4().hex[:8].upper()

    transfers = []

    if wh_context == "A":
        # Warehouse A is the active context
        needed_season = season_A
        # Wh B has opposite season — check if B has stock for what A needs
        # B has summer stock in Aug–Dec; A needs summer stock in Jan–Jul
        # So if A needs summer (Jan–Jul) and B has summer (Aug–Dec), no surplus from B right now
        # But per user spec: if date is Jan–Jul, A has less summer stock → B transfers summer to A
        #   and B's summer is Aug–Dec so B has winter stock to spare in Jan–Jul
        # Simplified: if A needs stock or is at start of its season → B sends surplus
        if needed_season == "Summer":
            from_wh  = "Warehouse B"
            to_wh    = "Warehouse A"
            action   = "Seasonal Transfer — Summer stock to Wh A"
            units    = round(100.0 + (month - 1) * 5.0, 1)  # dynamic based on month proximity
            context  = f"Wh A Summer | Date: {date_str}"
        else:  # Winter
            from_wh  = "Warehouse B"
            to_wh    = "Warehouse A"
            action   = "Seasonal Transfer — Winter stock to Wh A"
            units    = round(80.0 + (month - 8) * 4.0, 1)
            context  = f"Wh A Winter | Date: {date_str}"

        log_warehouse_transfer(
            agent_name="SeasonalAgent",
            from_wh=from_wh,
            to_wh=to_wh,
            units=units,
            context=context,
            order_id=order_id,
            action=action,
        )
        transfers.append({"from": from_wh, "to": to_wh, "units": units, "season": needed_season})

    else:  # wh_context == "B"
        needed_season = season_B
        if needed_season == "Summer":
            from_wh  = "Warehouse A"
            to_wh    = "Warehouse B"
            action   = "Seasonal Transfer — Summer stock to Wh B"
            units    = round(100.0 + (month - 8) * 5.0, 1)
            context  = f"Wh B Summer | Date: {date_str}"
        else:  # Winter
            from_wh  = "Warehouse A"
            to_wh    = "Warehouse B"
            action   = "Seasonal Transfer — Winter stock to Wh B"
            units    = round(80.0 + (month - 1) * 4.0, 1)
            context  = f"Wh B Winter | Date: {date_str}"

        log_warehouse_transfer(
            agent_name="SeasonalAgent",
            from_wh=from_wh,
            to_wh=to_wh,
            units=units,
            context=context,
            order_id=order_id,
            action=action,
        )
        transfers.append({"from": from_wh, "to": to_wh, "units": units, "season": needed_season})

    # Broadcast seasonal event via SSE
    _push({
        "type":              "seasonal_transfer",
        "order_id":          order_id,
        "warehouse_context": wh_context,
        "date":              date_str,
        "month":             month,
        "season_A":          season_A,
        "season_B":          season_B,
        "transfers":         transfers,
        "ts":                datetime.now().strftime("%H:%M:%S.%f")[:-3],
    }, None)

    return JSONResponse({
        "status":            "logged",
        "order_id":          order_id,
        "warehouse_context": wh_context,
        "date":              date_str,
        "season_A":          season_A,
        "season_B":          season_B,
        "transfers":         transfers,
        "message":           f"Seasonal transfer logged to warehouse_log.csv",
    })


# ── Simple warehouse transfer endpoint ───────────────────────────────────────

@app.post("/api/v1/warehouse_transfer")
async def warehouse_transfer(request: Request):
    """
    POST /api/v1/warehouse_transfer

    Body: {from_warehouse: str, to_warehouse: str}

    Logs a manual warehouse-to-warehouse transfer to warehouse_log.csv.
    Only called when the user has ticked the 'Log Transfer from Warehouse'
    checkbox on the shop frontend.
    """
    from automations.warehouse_logger import log_warehouse_transfer

    body       = await request.json()
    from_wh    = body.get("from_warehouse", "Warehouse A")
    to_wh      = body.get("to_warehouse",   "Warehouse B")
    units      = float(body.get("units", 50.0))   # default 50 units if not supplied
    order_id   = "WH-" + uuid.uuid4().hex[:8].upper()

    log_warehouse_transfer(
        agent_name="ManualTransfer",
        from_wh=from_wh,
        to_wh=to_wh,
        units=units,
        context="Manual",
        order_id=order_id,
        action="Manual Transfer",
    )

    return JSONResponse({
        "status":   "logged",
        "order_id": order_id,
        "from":     from_wh,
        "to":       to_wh,
        "units":    units,
        "message":  "Transfer logged to warehouse_log.csv",
    })



# ── WebSocket telemetry endpoint ──────────────────────────────────────────────

_ws_connections: Dict[str, List[WebSocket]] = defaultdict(list)
_ws_lock = threading.Lock()


@app.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket):
    """
    WebSocket endpoint consumed by mas-ops.html.

    Query params:
        order_id — subscribe to events for a specific order (optional).

    Pushes all SSE events relevant to that order (or all events if no order_id)
    in real-time.
    """
    await websocket.accept()
    order_id = websocket.query_params.get("order_id", "")

    ws_q: queue.Queue = queue.Queue(maxsize=300)

    # Register as a global AND per-order listener
    with _global_lock:
        _global_listeners.append(ws_q)
    if order_id:
        _order_listeners[order_id].append(ws_q)

    await websocket.send_text(json.dumps({"type": "connected", "order_id": order_id}))

    try:
        while True:
            try:
                msg = ws_q.get_nowait()
                await websocket.send_text(msg)
            except queue.Empty:
                await asyncio.sleep(0.04)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        with _global_lock:
            try:
                _global_listeners.remove(ws_q)
            except ValueError:
                pass
        if order_id and order_id in _order_listeners:
            try:
                _order_listeners[order_id].remove(ws_q)
            except ValueError:
                pass


# ── Legacy order endpoint (kept for backward-compat) ─────────────────────────

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


# ── Demand forecasting endpoints ──────────────────────────────────────────────

@app.get("/api/demand/history")
def get_demand_history_endpoint():
    df = load_demand_data()
    if "timestamp" in df.columns:
        df["timestamp"] = df["timestamp"].astype(str)
    return JSONResponse(df.to_dict(orient="records"))


@app.get("/api/demand/aggregate")
def get_demand_aggregate_endpoint():
    return JSONResponse(aggregate_demand())


@app.get("/api/demand/prediction")
def get_demand_prediction_endpoint():
    return JSONResponse(predict_demand())


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


# ── Phase 3.4 — /frontend/* routes (query-params preserved) ──────────────────

@app.get("/frontend/mas-ops.html", response_class=HTMLResponse)
async def serve_mas_ops_direct(request: Request):
    """Serve mas-ops.html at /frontend/mas-ops.html (used by shop.html redirect)."""
    p = BASE_DIR / "frontend" / "mas-ops.html"
    return p.read_text(encoding="utf-8")


@app.get("/frontend/shop.html", response_class=HTMLResponse)
async def serve_shop_direct():
    p = BASE_DIR / "frontend" / "shop.html"
    return p.read_text(encoding="utf-8")


@app.get("/demand", response_class=HTMLResponse)
async def serve_demand_forecast():
    """Serve the demand forecasting dashboard page."""
    p = BASE_DIR / "frontend" / "demand_forecast.html"
    return p.read_text(encoding="utf-8")


@app.get("/frontend/demand_forecast.html", response_class=HTMLResponse)
async def serve_demand_forecast_direct():
    """Serve demand_forecast.html at its direct URL path."""
    p = BASE_DIR / "frontend" / "demand_forecast.html"
    return p.read_text(encoding="utf-8")


@app.get("/demand_forecast.html", response_class=HTMLResponse)
async def serve_demand_forecast_html():
    """Serve demand_forecast.html at the root-level filename URL."""
    p = BASE_DIR / "frontend" / "demand_forecast.html"
    return p.read_text(encoding="utf-8")


@app.get("/mas_ops.html", response_class=HTMLResponse)
async def serve_mas_ops_html():
    """Serve mas-ops.html at the root-level filename URL (underscore variant)."""
    p = BASE_DIR / "frontend" / "mas-ops.html"
    return p.read_text(encoding="utf-8")
