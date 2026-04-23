"""
api/sales_router.py — Sales recording and reporting endpoints.

Sales Persons record sales (manual qty per product).
On each sale:
    - StoreInventory is auto-decremented
    - StoreInventoryAgent checks thresholds → creates StockAlert if needed
    - WebSocket broadcasts inventory change to Store Manager
"""

from __future__ import annotations

import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Optional

from db.database import get_db
from db.models import Sale, StoreInventory, StockAlert, Product, Store, User
from auth.dependencies import get_current_user

router = APIRouter(prefix="/api/stores", tags=["sales"])


# ── Global Hooks (set by app.py on startup) ───────────────────────────────────
_broadcast_fn = None
_sales_sync_agent = None

def set_broadcast_fn(fn):
    """Called by app.py to inject the WebSocket broadcast function."""
    global _broadcast_fn
    _broadcast_fn = fn

def set_sales_sync_agent(agent):
    """Called by app.py to inject the SalesSyncAgent."""
    global _sales_sync_agent
    _sales_sync_agent = agent


# ── Request schemas ────────────────────────────────────────────────────────────

class RecordSaleRequest(BaseModel):
    product_id: int
    quantity: float


# ── Threshold constants ───────────────────────────────────────────────────────

LOW_STOCK_THRESHOLD = 20.0     # units — trigger LOW_STOCK alert
CRITICAL_THRESHOLD  = 5.0      # units — trigger OUT_OF_STOCK alert


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/{store_id}/sales")
def record_sale(
    store_id: int,
    body: RecordSaleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Record a sale (Sales Person or Store Manager).
    Auto-decrements inventory and checks stock thresholds.
    """
    # Access check
    if current_user.role not in ("sales_person", "store_manager"):
        raise HTTPException(status_code=403, detail="Only sales persons and store managers can record sales")
    if current_user.store_id != store_id:
        raise HTTPException(status_code=403, detail="Cannot record sales for another store")

    # Validate product
    product = db.query(Product).filter(Product.id == body.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check inventory
    inv = db.query(StoreInventory).filter(
        StoreInventory.store_id == store_id,
        StoreInventory.product_id == body.product_id,
    ).first()

    if not inv:
        raise HTTPException(status_code=404, detail="Product not in store inventory")

    if inv.quantity < body.quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient stock. Available: {inv.quantity}, Requested: {body.quantity}",
        )

    # Record the sale
    sale = Sale(
        store_id=store_id,
        product_id=body.product_id,
        quantity=body.quantity,
        sale_price=product.unit_price * body.quantity,
        sold_by=current_user.id,
    )
    db.add(sale)

    # Decrement inventory
    inv.quantity -= body.quantity
    inv.last_updated = datetime.datetime.utcnow()

    # Check stock thresholds → auto-create alerts (StoreInventoryAgent behavior)
    alert_created = None
    if inv.quantity <= CRITICAL_THRESHOLD:
        alert = StockAlert(
            store_id=store_id,
            product_id=body.product_id,
            alert_type="out_of_stock",
            threshold=CRITICAL_THRESHOLD,
            current_level=inv.quantity,
        )
        db.add(alert)
        alert_created = "out_of_stock"
    elif inv.quantity <= LOW_STOCK_THRESHOLD:
        # Only create if no unresolved low_stock alert exists for this product
        existing = db.query(StockAlert).filter(
            StockAlert.store_id == store_id,
            StockAlert.product_id == body.product_id,
            StockAlert.alert_type == "low_stock",
            StockAlert.is_resolved == False,
        ).first()
        if not existing:
            alert = StockAlert(
                store_id=store_id,
                product_id=body.product_id,
                alert_type="low_stock",
                threshold=LOW_STOCK_THRESHOLD,
                current_level=inv.quantity,
            )
            db.add(alert)
            alert_created = "low_stock"

    db.commit()

    # Inform SalesSyncAgent to publish SALE_RECORDED event to MessageBus
    if _sales_sync_agent:
        try:
            _sales_sync_agent.record_sale_event(sale.id)
        except Exception:
            pass

    # Broadcast via WebSocket (non-blocking)
    if _broadcast_fn:
        try:
            import asyncio
            msg = {
                "type": "inventory_update",
                "store_id": store_id,
                "product_id": body.product_id,
                "product_name": product.name,
                "new_quantity": inv.quantity,
                "change": -body.quantity,
                "change_type": "sale",
                "alert": alert_created,
            }
            asyncio.get_event_loop().create_task(_broadcast_fn(msg))
        except Exception:
            pass  # WebSocket broadcast is best-effort

    return {
        "sale_id": sale.id,
        "product_name": product.name,
        "quantity_sold": body.quantity,
        "sale_price": sale.sale_price,
        "remaining_stock": inv.quantity,
        "alert": alert_created,
    }


@router.get("/{store_id}/sales")
def get_sales(
    store_id: int,
    days: int = Query(7, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get sales history for a store, filtered by date range."""
    # Access check
    if current_user.role == "regional_manager":
        store = db.query(Store).filter(Store.id == store_id).first()
        if not store or store.region_id != current_user.region_id:
            raise HTTPException(status_code=403, detail="Access denied")
    elif current_user.store_id != store_id:
        raise HTTPException(status_code=403, detail="Access denied to this store")

    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    sales = db.query(Sale).options(
        joinedload(Sale.product),
        joinedload(Sale.sold_by_user),
    ).filter(
        Sale.store_id == store_id,
        Sale.sold_at >= since,
    ).order_by(Sale.sold_at.desc()).limit(200).all()

    return [s.to_dict() for s in sales]


@router.get("/{store_id}/sales/summary")
def get_sales_summary(
    store_id: int,
    days: int = Query(7, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get aggregated sales summary for a store."""
    if current_user.role == "regional_manager":
        store = db.query(Store).filter(Store.id == store_id).first()
        if not store or store.region_id != current_user.region_id:
            raise HTTPException(status_code=403, detail="Access denied")
    elif current_user.store_id != store_id:
        raise HTTPException(status_code=403, detail="Access denied to this store")

    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    # Total sales
    totals = db.query(
        func.count(Sale.id).label("count"),
        func.sum(Sale.quantity).label("total_units"),
        func.sum(Sale.sale_price).label("total_revenue"),
    ).filter(
        Sale.store_id == store_id,
        Sale.sold_at >= since,
    ).first()

    # Top products
    top_products = db.query(
        Product.name,
        func.sum(Sale.quantity).label("total_qty"),
        func.sum(Sale.sale_price).label("total_revenue"),
    ).join(Sale.product).filter(
        Sale.store_id == store_id,
        Sale.sold_at >= since,
    ).group_by(Product.name).order_by(func.sum(Sale.quantity).desc()).limit(5).all()

    return {
        "period_days": days,
        "total_sales": totals.count or 0,
        "total_units": round(totals.total_units or 0, 1),
        "total_revenue": round(totals.total_revenue or 0, 2),
        "top_products": [
            {"name": p.name, "units": round(p.total_qty, 1), "revenue": round(p.total_revenue, 2)}
            for p in top_products
        ],
    }
