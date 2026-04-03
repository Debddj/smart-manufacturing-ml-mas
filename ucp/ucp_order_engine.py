"""
UCP Capability Handler — Agentic capability negotiation layer.

Implements the UCP handshake protocol:
  1. Agent queries /profile → discovers available capabilities
  2. Agent negotiates extensions (discounts, loyalty, etc.)
  3. Agent executes capability (checkout, discovery, cart ops)

This eliminates the N×N integration bottleneck described in the UCP spec:
  - No bespoke per-surface integrations needed
  - Agents auto-discover what the business supports
  - Business logic stays server-side (owner retains control)
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
import time
import uuid


SUPPORTED_CAPABILITIES = {
    "discovery":     ["search", "browse", "inventory_check", "product_detail"],
    "cart":          ["add_item", "remove_item", "update_qty", "get_cart", "clear_cart"],
    "checkout":      ["initiate", "apply_discount", "confirm", "get_order"],
    "post_purchase": ["track_order", "request_return", "get_invoice"],
}


class UCPCapabilityHandler:
    """
    UCP capability negotiation and execution engine.

    Agents call negotiate() to establish a session, then execute()
    to run commerce operations — all through a single standardised interface.
    """

    def __init__(self, catalog, order_engine):
        self.catalog      = catalog
        self.order_engine = order_engine
        self._sessions: Dict[str, dict] = {}

    def negotiate(
        self,
        agent_id:   str,
        requested:  List[str],
        extensions: Optional[List[str]] = None,
    ) -> dict:
        """
        UCP capability negotiation handshake.

        Agent declares what it wants → server confirms what it can deliver.
        Returns a session token and confirmed capability set.
        """
        profile   = self.catalog.ucp_profile()
        available = set()
        for cap_group in profile["capabilities"].values():
            if isinstance(cap_group, dict) and cap_group.get("enabled"):
                for k, v in cap_group.items():
                    if k != "enabled" and v:
                        available.add(k)

        confirmed = [r for r in requested if r in available
                     or any(r in caps for caps in SUPPORTED_CAPABILITIES.values())]

        session_id = f"ucp-{uuid.uuid4().hex[:12]}"
        self._sessions[session_id] = {
            "agent_id":   agent_id,
            "confirmed":  confirmed,
            "extensions": extensions or [],
            "created_at": time.time(),
            "cart":       {},
        }

        return {
            "session_id":          session_id,
            "confirmed_capabilities": confirmed,
            "extensions_granted":  [
                e for e in (extensions or [])
                if e in profile.get("extensions", {})
                and profile["extensions"].get(e)
            ],
            "transport":    profile["transport"],
            "ucp_version":  profile["ucp_version"],
        }

    def execute(
        self,
        session_id:  str,
        capability:  str,
        params:      Dict[str, Any],
    ) -> dict:
        """
        Execute a UCP capability within an active session.
        """
        session = self._sessions.get(session_id)
        if not session:
            return {"error": "Invalid or expired session", "code": 401}

        dispatch = {
            "search":         self._exec_search,
            "inventory_check":self._exec_inventory,
            "product_detail": self._exec_detail,
            "add_item":       self._exec_cart_add,
            "remove_item":    self._exec_cart_remove,
            "update_qty":     self._exec_cart_update,
            "get_cart":       self._exec_cart_get,
            "initiate":       self._exec_checkout_initiate,
            "confirm":        self._exec_checkout_confirm,
            "get_order":      self._exec_get_order,
            "track_order":    self._exec_track_order,
        }

        fn = dispatch.get(capability)
        if not fn:
            return {"error": f"Capability '{capability}' not supported", "code": 400}

        return fn(session, params)

    # ── Capability implementations ─────────────────────────────────────────────

    def _exec_search(self, session, params):
        results = self.catalog.search(
            query    = params.get("query", ""),
            category = params.get("category"),
            max_results = params.get("limit", 10),
        )
        return {
            "capability": "search",
            "count":      len(results),
            "results":    [p.to_ucp_listing() for p in results],
        }

    def _exec_inventory(self, session, params):
        sku = params.get("sku")
        return self.catalog.get_inventory(sku) if sku else {"error": "sku required"}

    def _exec_detail(self, session, params):
        p = self.catalog.get(params.get("sku", ""))
        return p.to_ucp_listing() if p else {"error": "Product not found"}

    def _exec_cart_add(self, session, params):
        sku = params.get("sku")
        qty = int(params.get("quantity", 1))
        p   = self.catalog.get(sku)
        if not p:
            return {"error": f"Product {sku} not found"}
        cart = session["cart"]
        cart[sku] = cart.get(sku, 0) + qty
        return {"status": "added", "sku": sku, "cart_qty": cart[sku]}

    def _exec_cart_remove(self, session, params):
        sku = params.get("sku")
        session["cart"].pop(sku, None)
        return {"status": "removed", "sku": sku}

    def _exec_cart_update(self, session, params):
        sku = params.get("sku")
        qty = int(params.get("quantity", 0))
        if qty <= 0:
            session["cart"].pop(sku, None)
        else:
            session["cart"][sku] = qty
        return {"status": "updated", "sku": sku, "quantity": qty}

    def _exec_cart_get(self, session, params):
        items = []
        total = 0.0
        for sku, qty in session["cart"].items():
            p = self.catalog.get(sku)
            if p:
                line_total = p.unit_price * qty
                total     += line_total
                items.append({
                    "sku":        sku,
                    "name":       p.name,
                    "quantity":   qty,
                    "unit_price": p.unit_price,
                    "line_total": round(line_total, 2),
                })
        return {"items": items, "item_count": len(items), "total": round(total, 2)}

    def _exec_checkout_initiate(self, session, params):
        cart = self._exec_cart_get(session, {})
        if not cart["items"]:
            return {"error": "Cart is empty"}
        checkout_id = f"chk_{uuid.uuid4().hex[:10]}"
        return {
            "checkout_id": checkout_id,
            "cart_summary": cart,
            "payment_methods": ["purchase_order", "credit_card", "stripe"],
            "fulfillment_options": [
                {"id": "standard", "label": "Standard (3-5 days)", "cost": 0},
                {"id": "express",  "label": "Express (1-2 days)",  "cost": round(cart["total"] * 0.05, 2)},
                {"id": "bulk",     "label": "Bulk freight",        "cost": 0, "min_value": 5000},
            ],
        }

    def _exec_checkout_confirm(self, session, params):
        order = self.order_engine.create_order(
            cart    = session["cart"],
            catalog = self.catalog,
            customer_id = session["agent_id"],
            fulfillment = params.get("fulfillment", "standard"),
            payment     = params.get("payment_method", "purchase_order"),
        )
        session["cart"] = {}
        return order

    def _exec_get_order(self, session, params):
        return self.order_engine.get_order(params.get("order_id", ""))

    def _exec_track_order(self, session, params):
        return self.order_engine.track_order(params.get("order_id", ""))