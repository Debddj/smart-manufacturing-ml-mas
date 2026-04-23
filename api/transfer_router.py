"""
api/transfer_router.py — Inter-store stock transfer endpoints.
"""

from __future__ import annotations
import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Optional

from db.database import get_db
from db.models import Store, StoreInventory, TransferRequest, Product, User
from auth.dependencies import get_current_user

router = APIRouter(prefix="/api", tags=["transfers"])

# ── Global Hooks (set by app.py on startup) ───────────────────────────────────
_inter_store_agent = None

def set_inter_store_agent(agent):
    global _inter_store_agent
    _inter_store_agent = agent

class TransferRequestBody(BaseModel):
    from_store_id: int
    to_store_id: int
    product_id: int
    quantity: float


@router.get("/stores/{store_id}/nearby")
def nearby_stores(store_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    if current_user.role == "regional_manager":
        if store.region_id != current_user.region_id:
            raise HTTPException(status_code=403, detail="Not in your region")
    elif current_user.store_id != store_id:
        raise HTTPException(status_code=403, detail="Access denied")

    nearby = db.query(Store).filter(Store.region_id == store.region_id, Store.id != store_id, Store.is_active == True).all()
    result = []
    for ns in nearby:
        total_stock = db.query(func.sum(StoreInventory.quantity)).filter(StoreInventory.store_id == ns.id).scalar() or 0
        result.append({"id": ns.id, "name": ns.name, "store_code": ns.store_code, "total_stock": round(total_stock, 1)})
    return result


@router.get("/stores/{store_id}/product-availability/{product_id}")
def check_product_availability(store_id: int, product_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).first()
    product = db.query(Product).filter(Product.id == product_id).first()
    if not store or not product:
        raise HTTPException(status_code=404, detail="Store or product not found")

    nearby = db.query(Store).filter(Store.region_id == store.region_id, Store.id != store_id, Store.is_active == True).all()
    available_at = []
    for ns in nearby:
        inv = db.query(StoreInventory).filter(StoreInventory.store_id == ns.id, StoreInventory.product_id == product_id).first()
        if inv and inv.quantity > 0:
            available_at.append({"store_id": ns.id, "store_name": ns.name, "store_code": ns.store_code, "quantity": round(inv.quantity, 1), "suggestion": f"Product available at {ns.name} — {round(inv.quantity, 1)} units in stock"})
    return {"product_name": product.name, "your_store": store.name, "available_at": available_at, "total_available": sum(a["quantity"] for a in available_at)}


@router.post("/transfers/request")
def create_transfer_request(body: TransferRequestBody, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ("store_manager", "regional_manager"):
        raise HTTPException(status_code=403, detail="Only managers can request transfers")
    from_store = db.query(Store).filter(Store.id == body.from_store_id).first()
    to_store = db.query(Store).filter(Store.id == body.to_store_id).first()
    if not from_store or not to_store:
        raise HTTPException(status_code=404, detail="Store not found")
    if from_store.region_id != to_store.region_id:
        raise HTTPException(status_code=400, detail="Transfers only between stores in the same region")
    inv = db.query(StoreInventory).filter(StoreInventory.store_id == body.from_store_id, StoreInventory.product_id == body.product_id).first()
    if not inv or inv.quantity < body.quantity:
        raise HTTPException(status_code=400, detail="Insufficient stock at source store")
    transfer = TransferRequest(from_store_id=body.from_store_id, to_store_id=body.to_store_id, product_id=body.product_id, quantity=body.quantity, status="pending", requested_by=current_user.id)
    db.add(transfer)
    db.commit()

    if _inter_store_agent:
        try:
            _inter_store_agent.bus.publish(
                message_type="transfer_request",
                sender="TransferRouter",
                payload={"transfer_id": transfer.id, "from_store_id": transfer.from_store_id, "to_store_id": transfer.to_store_id, "quantity": transfer.quantity},
                priority=3 # Priority.ACTION
            )
        except Exception:
            pass

    return transfer.to_dict()


@router.get("/transfers")
def list_transfers(status: Optional[str] = Query(None), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(TransferRequest).options(joinedload(TransferRequest.from_store), joinedload(TransferRequest.to_store), joinedload(TransferRequest.product))
    if current_user.role == "regional_manager":
        store_ids = [s.id for s in db.query(Store).filter(Store.region_id == current_user.region_id).all()]
        query = query.filter((TransferRequest.from_store_id.in_(store_ids)) | (TransferRequest.to_store_id.in_(store_ids)))
    else:
        query = query.filter((TransferRequest.from_store_id == current_user.store_id) | (TransferRequest.to_store_id == current_user.store_id))
    if status:
        query = query.filter(TransferRequest.status == status)
    transfers = query.order_by(TransferRequest.created_at.desc()).limit(50).all()
    return [t.to_dict() for t in transfers]


@router.put("/transfers/{transfer_id}/approve")
def approve_transfer(transfer_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ("store_manager", "regional_manager"):
        raise HTTPException(status_code=403, detail="Only managers can approve transfers")
    transfer = db.query(TransferRequest).filter(TransferRequest.id == transfer_id).first()
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer not found")
    if transfer.status != "pending":
        raise HTTPException(status_code=400, detail=f"Transfer is already {transfer.status}")
    if current_user.role == "store_manager" and current_user.store_id != transfer.from_store_id:
        raise HTTPException(status_code=403, detail="Only the source store manager can approve")
    transfer.status = "approved"
    transfer.approved_by = current_user.id
    db.commit()

    if _inter_store_agent:
        try:
            _inter_store_agent.bus.publish(
                message_type="transfer_approved",
                sender="TransferRouter",
                payload={"transfer_id": transfer.id},
                priority=2 # Priority.INFO
            )
        except Exception:
            pass

    return transfer.to_dict()


@router.put("/transfers/{transfer_id}/complete")
def complete_transfer(transfer_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    transfer = db.query(TransferRequest).filter(TransferRequest.id == transfer_id).first()
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer not found")
    if transfer.status != "approved":
        raise HTTPException(status_code=400, detail="Transfer must be approved first")
    from_inv = db.query(StoreInventory).filter(StoreInventory.store_id == transfer.from_store_id, StoreInventory.product_id == transfer.product_id).first()
    if not from_inv or from_inv.quantity < transfer.quantity:
        raise HTTPException(status_code=400, detail="Source store no longer has sufficient stock")
    from_inv.quantity -= transfer.quantity
    from_inv.last_updated = datetime.datetime.utcnow()
    to_inv = db.query(StoreInventory).filter(StoreInventory.store_id == transfer.to_store_id, StoreInventory.product_id == transfer.product_id).first()
    if to_inv:
        to_inv.quantity += transfer.quantity
        to_inv.last_updated = datetime.datetime.utcnow()
    else:
        to_inv = StoreInventory(store_id=transfer.to_store_id, product_id=transfer.product_id, quantity=transfer.quantity)
        db.add(to_inv)
    transfer.status = "completed"
    transfer.completed_at = datetime.datetime.utcnow()
    db.commit()
    return transfer.to_dict()
