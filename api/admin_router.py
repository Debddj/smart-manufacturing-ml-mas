"""
api/admin_router.py — Store creation and admin endpoints.

Regional Managers can dynamically create new stores with auto-generated
credentials for Store Manager + Sales Person.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import Store, User, StoreInventory, Product, Region
from auth.dependencies import get_current_user, require_role

router = APIRouter(prefix="/api/admin", tags=["admin"])


class CreateStoreRequest(BaseModel):
    name: str
    region_id: int


class CreateStoreResponse(BaseModel):
    store: dict
    credentials: list


@router.post("/stores/create", response_model=CreateStoreResponse)
def create_store(
    body: CreateStoreRequest,
    current_user: User = Depends(require_role("regional_manager")),
    db: Session = Depends(get_db),
):
    """
    Create a new store with auto-generated staff credentials.

    Only Regional Managers can create stores, and only in their own region.
    Auto-generates:
        - Store code (e.g., STORE-N5)
        - Store Manager account
        - Sales Person account
        - Inventory seeded at regional average
    """
    # Verify region access
    if current_user.region_id != body.region_id:
        raise HTTPException(status_code=403, detail="Cannot create stores outside your region")

    region = db.query(Region).filter(Region.id == body.region_id).first()
    if not region:
        raise HTTPException(status_code=404, detail="Region not found")

    # Generate store code
    existing_count = db.query(Store).filter(Store.region_id == body.region_id).count()
    region_prefix = region.name[0].upper()  # N or S
    store_number = existing_count + 1
    store_code = f"STORE-{region_prefix}{store_number}"

    # Check for duplicate code
    while db.query(Store).filter(Store.store_code == store_code).first():
        store_number += 1
        store_code = f"STORE-{region_prefix}{store_number}"

    # Create the store
    store = Store(
        name=body.name,
        store_code=store_code,
        region_id=body.region_id,
    )
    db.add(store)
    db.flush()

    # Generate user suffix
    suffix = f"{region_prefix.lower()}{store_number}"

    # Create Store Manager
    sm_user_id = f"sm_{suffix}"
    sm_password = "password123"  # same default as seeded users
    sm = User(
        user_id=sm_user_id,
        password=sm_password,
        display_name=f"Store Manager {store_code}",
        role="store_manager",
        store_id=store.id,
        region_id=body.region_id,
    )
    db.add(sm)

    # Create Sales Person
    sp_user_id = f"sp_{suffix}"
    sp_password = "password123"  # same default as seeded users
    sp = User(
        user_id=sp_user_id,
        password=sp_password,
        display_name=f"Sales Person {store_code}",
        role="sales_person",
        store_id=store.id,
        region_id=body.region_id,
    )
    db.add(sp)

    # Seed inventory — use regional average or default 100 units
    products = db.query(Product).filter(Product.is_active == True).all()
    region_stores = db.query(Store).filter(
        Store.region_id == body.region_id,
        Store.id != store.id,
    ).all()

    for product in products:
        # Calculate regional average stock
        if region_stores:
            avg_qty = 0
            count = 0
            for rs in region_stores:
                inv = db.query(StoreInventory).filter(
                    StoreInventory.store_id == rs.id,
                    StoreInventory.product_id == product.id,
                ).first()
                if inv:
                    avg_qty += inv.quantity
                    count += 1
            avg_qty = avg_qty / max(count, 1)
        else:
            avg_qty = 100.0

        inv = StoreInventory(
            store_id=store.id,
            product_id=product.id,
            quantity=round(avg_qty, 1),
        )
        db.add(inv)

    db.commit()

    credentials = [
        {"user_id": sm_user_id, "password": sm_password, "role": "store_manager"},
        {"user_id": sp_user_id, "password": sp_password, "role": "sales_person"},
    ]

    return CreateStoreResponse(
        store={
            "id": store.id,
            "name": store.name,
            "store_code": store_code,
            "region": region.name,
        },
        credentials=credentials,
    )
