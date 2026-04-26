"""
api/regional_router.py — Regional Manager analytics endpoints.

Provides region-wide KPIs, store comparisons, and product analytics.
Access restricted to regional_manager role.
"""

from __future__ import annotations

import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Optional

from db.database import get_db
from db.models import (
    Region, Store, StoreInventory, Sale, Product, StockAlert, User, Warehouse,
)
from auth.dependencies import get_current_user, require_role

router = APIRouter(prefix="/api/regions", tags=["regions"])


@router.get("/{region_id}/overview")
def region_overview(
    region_id: int,
    days: int = Query(7, ge=1, le=365),
    current_user: User = Depends(require_role("regional_manager")),
    db: Session = Depends(get_db),
):
    """Aggregated KPIs for a region."""
    if current_user.region_id != region_id:
        raise HTTPException(status_code=403, detail="Not your region")

    region = db.query(Region).filter(Region.id == region_id).first()
    if not region:
        raise HTTPException(status_code=404, detail="Region not found")

    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    stores = db.query(Store).filter(Store.region_id == region_id, Store.is_active == True).all()
    store_ids = [s.id for s in stores]

    # Total inventory across region
    total_inv = db.query(func.sum(StoreInventory.quantity)).filter(
        StoreInventory.store_id.in_(store_ids)
    ).scalar() or 0

    # Total sales in period
    sales_data = db.query(
        func.count(Sale.id),
        func.sum(Sale.quantity),
        func.sum(Sale.sale_price),
    ).filter(
        Sale.store_id.in_(store_ids),
        Sale.sold_at >= since,
    ).first()

    # Active alerts
    active_alerts = db.query(StockAlert).filter(
        StockAlert.store_id.in_(store_ids),
        StockAlert.is_resolved == False,
    ).count()

    # Warehouse
    warehouse = db.query(Warehouse).filter(Warehouse.region_id == region_id).first()

    return {
        "region_name": region.name,
        "store_count": len(stores),
        "period_days": days,
        "total_inventory": round(total_inv, 1),
        "total_sales": sales_data[0] or 0,
        "total_units_sold": round(sales_data[1] or 0, 1),
        "total_revenue": round(sales_data[2] or 0, 2),
        "active_alerts": active_alerts,
        "warehouse_stock": round(warehouse.current_stock, 1) if warehouse else 0,
    }


@router.get("/{region_id}/stores")
def region_stores(
    region_id: int,
    days: int = Query(7, ge=1, le=365),
    current_user: User = Depends(require_role("regional_manager")),
    db: Session = Depends(get_db),
):
    """All stores in the region with performance data."""
    if current_user.region_id != region_id:
        raise HTTPException(status_code=403, detail="Not your region")

    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    stores = db.query(Store).filter(Store.region_id == region_id, Store.is_active == True).all()

    result = []
    for store in stores:
        # Inventory total
        inv_total = db.query(func.sum(StoreInventory.quantity)).filter(
            StoreInventory.store_id == store.id
        ).scalar() or 0

        # Sales in period
        sales = db.query(
            func.sum(Sale.quantity),
            func.sum(Sale.sale_price),
        ).filter(
            Sale.store_id == store.id,
            Sale.sold_at >= since,
        ).first()

        alerts = db.query(StockAlert).filter(
            StockAlert.store_id == store.id,
            StockAlert.is_resolved == False,
        ).count()

        result.append({
            "id": store.id,
            "name": store.name,
            "store_code": store.store_code,
            "total_inventory": round(inv_total, 1),
            "units_sold": round(sales[0] or 0, 1),
            "revenue": round(sales[1] or 0, 2),
            "active_alerts": alerts,
        })

    return result


@router.get("/{region_id}/sales/by-store")
def region_sales_by_store(
    region_id: int,
    days: int = Query(7, ge=1, le=365),
    current_user: User = Depends(require_role("regional_manager")),
    db: Session = Depends(get_db),
):
    """Store-wise sales comparison."""
    if current_user.region_id != region_id:
        raise HTTPException(status_code=403, detail="Not your region")

    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    results = db.query(
        Store.name,
        Store.store_code,
        func.sum(Sale.quantity).label("total_units"),
        func.sum(Sale.sale_price).label("total_revenue"),
        func.count(Sale.id).label("sale_count"),
    ).join(Sale, Sale.store_id == Store.id).filter(
        Store.region_id == region_id,
        Sale.sold_at >= since,
    ).group_by(Store.name, Store.store_code).all()

    return [
        {
            "store_name": r.name,
            "store_code": r.store_code,
            "total_units": round(r.total_units or 0, 1),
            "total_revenue": round(r.total_revenue or 0, 2),
            "sale_count": r.sale_count or 0,
        }
        for r in results
    ]


@router.get("/{region_id}/products/top")
def region_top_products(
    region_id: int,
    days: int = Query(7, ge=1, le=365),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(require_role("regional_manager")),
    db: Session = Depends(get_db),
):
    """Highest-demand products across the region."""
    if current_user.region_id != region_id:
        raise HTTPException(status_code=403, detail="Not your region")

    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    store_ids = [s.id for s in db.query(Store).filter(Store.region_id == region_id).all()]

    results = db.query(
        Product.name,
        Product.sku,
        func.sum(Sale.quantity).label("total_units"),
        func.sum(Sale.sale_price).label("total_revenue"),
    ).join(Sale.product).filter(
        Sale.store_id.in_(store_ids),
        Sale.sold_at >= since,
    ).group_by(Product.name, Product.sku).order_by(
        func.sum(Sale.quantity).desc()
    ).limit(limit).all()

    return [
        {
            "name": r.name,
            "sku": r.sku,
            "total_units": round(r.total_units or 0, 1),
            "total_revenue": round(r.total_revenue or 0, 2),
        }
        for r in results
    ]


@router.get("/{region_id}/stores/underperforming")
def region_underperforming_stores(
    region_id: int,
    days: int = Query(7, ge=1, le=365),
    current_user: User = Depends(require_role("regional_manager")),
    db: Session = Depends(get_db),
):
    """Stores performing below regional average (by >15%)."""
    if current_user.region_id != region_id:
        raise HTTPException(status_code=403, detail="Not your region")

    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    stores = db.query(Store).filter(Store.region_id == region_id, Store.is_active == True).all()

    store_revenue = {}
    for store in stores:
        rev = db.query(func.sum(Sale.sale_price)).filter(
            Sale.store_id == store.id,
            Sale.sold_at >= since,
        ).scalar() or 0
        store_revenue[store.id] = {"name": store.name, "code": store.store_code, "revenue": float(rev)}

    if not store_revenue:
        return []

    avg_revenue = sum(s["revenue"] for s in store_revenue.values()) / len(store_revenue)
    threshold = avg_revenue * 0.85  # 15% below average

    return [
        {
            "store_id": sid,
            "name": data["name"],
            "store_code": data["code"],
            "revenue": round(data["revenue"], 2),
            "regional_average": round(avg_revenue, 2),
            "deficit_pct": round((1 - data["revenue"] / max(avg_revenue, 0.01)) * 100, 1),
        }
        for sid, data in store_revenue.items()
        if data["revenue"] < threshold
    ]


@router.get("/{region_id}/stores/forecast")
def stores_forecast(
    region_id: int,
    current_user: User = Depends(require_role("regional_manager")),
    db: Session = Depends(get_db),
):
    """
    Return per-store inventory with product-level details and demand predictions
    for every store in this region.
    """
    if current_user.region_id != region_id:
        raise HTTPException(403, "Access denied to this region")

    region = db.query(Region).filter(Region.id == region_id).first()
    if not region:
        raise HTTPException(404, "Region not found")

    stores = db.query(Store).filter(Store.region_id == region_id).all()
    result = []

    for store in stores:
        inventory = (
            db.query(StoreInventory, Product)
            .join(Product, StoreInventory.product_id == Product.id)
            .filter(StoreInventory.store_id == store.id)
            .all()
        )

        products_data = []
        for inv, prod in inventory:
            # Simple demand classification based on stock vs base_demand
            ratio = inv.quantity / max(prod.base_demand, 1)
            if ratio < 1.5:
                demand_status = "HIGH"
            elif ratio < 3.0:
                demand_status = "MEDIUM"
            else:
                demand_status = "LOW"

            products_data.append({
                "product_id": prod.id,
                "sku": prod.sku,
                "name": prod.name,
                "category": prod.category,
                "unit_price": prod.unit_price,
                "current_stock": inv.quantity,
                "base_demand": prod.base_demand,
                "demand_status": demand_status,
            })

        result.append({
            "store_id": store.id,
            "name": store.name,
            "store_code": store.store_code,
            "product_count": len(products_data),
            "total_stock": sum(p["current_stock"] for p in products_data),
            "products": products_data,
        })

    return result

