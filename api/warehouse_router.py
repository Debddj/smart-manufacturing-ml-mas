"""
api/warehouse_router.py — Warehouse management and cross-region transfer endpoints.
"""

from __future__ import annotations
import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from db.database import get_db
from db.models import Warehouse, WarehouseTransfer, Region, Store, Sale, User
from auth.dependencies import get_current_user, require_role

router = APIRouter(prefix="/api/warehouses", tags=["warehouses"])


class WarehouseTransferRequest(BaseModel):
    from_warehouse_id: int
    to_warehouse_id: int
    units: float
    reason: str = ""


@router.get("")
def list_warehouses(current_user: User = Depends(require_role("regional_manager")), db: Session = Depends(get_db)):
    warehouses = db.query(Warehouse).all()
    return [{"id": w.id, "name": w.name, "region_id": w.region_id, "capacity": w.capacity, "current_stock": round(w.current_stock, 1), "utilization_pct": round(w.current_stock / max(w.capacity, 1) * 100, 1)} for w in warehouses]


@router.get("/imbalance")
def detect_imbalance(current_user: User = Depends(require_role("regional_manager")), db: Session = Depends(get_db)):
    """Detect stock imbalances across regional warehouses."""
    warehouses = db.query(Warehouse).all()
    if len(warehouses) < 2:
        return {"imbalance_detected": False, "warehouses": []}

    avg_util = sum(w.current_stock / max(w.capacity, 1) for w in warehouses) / len(warehouses)
    results = []
    imbalance = False
    for wh in warehouses:
        util = wh.current_stock / max(wh.capacity, 1)
        status = "balanced"
        if util < 0.25:
            status = "critical_low"
            imbalance = True
        elif util < 0.40:
            status = "low"
            imbalance = True
        elif util > 0.75:
            status = "surplus"
        results.append({"id": wh.id, "name": wh.name, "current_stock": round(wh.current_stock, 1), "capacity": wh.capacity, "utilization_pct": round(util * 100, 1), "status": status})
    return {"imbalance_detected": imbalance, "average_utilization": round(avg_util * 100, 1), "warehouses": results}


@router.get("/transfers")
def list_warehouse_transfers(current_user: User = Depends(require_role("regional_manager")), db: Session = Depends(get_db)):
    transfers = db.query(WarehouseTransfer).order_by(WarehouseTransfer.created_at.desc()).limit(50).all()
    result = []
    for t in transfers:
        from_wh = db.query(Warehouse).filter(Warehouse.id == t.from_warehouse_id).first()
        to_wh = db.query(Warehouse).filter(Warehouse.id == t.to_warehouse_id).first()
        result.append({"id": t.id, "from_warehouse": from_wh.name if from_wh else None, "to_warehouse": to_wh.name if to_wh else None, "units": t.units, "reason": t.reason, "status": t.status, "created_at": t.created_at.isoformat() if t.created_at else None})
    return result


@router.post("/transfer")
def trigger_warehouse_transfer(body: WarehouseTransferRequest, current_user: User = Depends(require_role("regional_manager")), db: Session = Depends(get_db)):
    from_wh = db.query(Warehouse).filter(Warehouse.id == body.from_warehouse_id).first()
    to_wh = db.query(Warehouse).filter(Warehouse.id == body.to_warehouse_id).first()
    if not from_wh or not to_wh:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    if from_wh.current_stock < body.units:
        raise HTTPException(status_code=400, detail="Insufficient stock in source warehouse")
    from_wh.current_stock -= body.units
    to_wh.current_stock += body.units
    transfer = WarehouseTransfer(from_warehouse_id=body.from_warehouse_id, to_warehouse_id=body.to_warehouse_id, units=body.units, reason=body.reason, transfer_type="cross_region", status="completed", completed_at=datetime.datetime.utcnow())
    db.add(transfer)
    db.commit()
    return {"transfer_id": transfer.id, "from": from_wh.name, "to": to_wh.name, "units": body.units, "status": "completed"}


# NOTE: This parameterized route MUST come AFTER all static routes (/imbalance, /transfers, /transfer)
# otherwise FastAPI will try to parse "imbalance" or "transfers" as a warehouse_id int and return 422.
@router.get("/{warehouse_id}")
def get_warehouse(warehouse_id: int, current_user: User = Depends(require_role("regional_manager")), db: Session = Depends(get_db)):
    wh = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    region = db.query(Region).filter(Region.id == wh.region_id).first()
    stores = db.query(Store).filter(Store.region_id == wh.region_id, Store.is_active == True).all()
    return {"id": wh.id, "name": wh.name, "region": region.name if region else None, "capacity": wh.capacity, "current_stock": round(wh.current_stock, 1), "utilization_pct": round(wh.current_stock / max(wh.capacity, 1) * 100, 1), "stores_served": [{"id": s.id, "name": s.name, "code": s.store_code} for s in stores]}
