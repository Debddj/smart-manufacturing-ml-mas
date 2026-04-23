"""
db/seed.py — Seed the database with initial data.

Creates:
    - 2 Regions: Kolkata, Kashmir
    - 2 Warehouses: Warehouse-Kolkata, Warehouse-Kashmir
    - 8 Stores: Store-KOL1..KOL4 (Kolkata), Store-KAS1..KAS4 (Kashmir)
    - 5 Products (from ProductCatalog.DEFAULT_PRODUCTS)
    - 40 StoreInventory rows (8 stores × 5 products, 100 units each)
    - 18 Users: 8 Store Managers + 8 Sales Persons + 2 Regional Managers

Usage:
    python -m db.seed          # run standalone
    from db.seed import seed_all; seed_all()  # from code
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import SessionLocal, init_db
from db.models import User, Region, Store, Product, StoreInventory, Warehouse


# ── Product definitions (mirrors ucp_product_catalog.py) ──────────────────────

DEFAULT_PRODUCTS = [
    {"sku": "SKU-WIDGET-A",   "name": "Industrial Precision Widget A", "category": "electronics",     "unit_price": 24.99,  "base_demand": 85.0,  "description": "High-precision industrial component for manufacturing lines."},
    {"sku": "SKU-SENSOR-PRO", "name": "Smart IoT Sensor Module Pro",   "category": "sensors",         "unit_price": 89.50,  "base_demand": 62.0,  "description": "Multi-protocol IoT sensor with edge AI capability."},
    {"sku": "SKU-ACTUATOR-X", "name": "Linear Actuator X-Series",      "category": "mechanical",      "unit_price": 156.00, "base_demand": 40.0,  "description": "Heavy-duty linear actuator for automated assembly systems."},
    {"sku": "SKU-CTRL-UNIT",  "name": "PLC Control Unit v4",           "category": "control-systems", "unit_price": 445.00, "base_demand": 22.0,  "description": "Programmable logic controller with modbus/ethernet support."},
    {"sku": "SKU-PWR-SUPPLY", "name": "48V Industrial Power Supply",   "category": "power",           "unit_price": 67.99,  "base_demand": 55.0,  "description": "DIN-rail mount 48V/20A industrial power supply unit."},
]

# ── Store definitions ─────────────────────────────────────────────────────────

STORES = {
    "Kolkata": [
        {"name": "Kolkata Store 1", "code": "STORE-KOL1"},
        {"name": "Kolkata Store 2", "code": "STORE-KOL2"},
        {"name": "Kolkata Store 3", "code": "STORE-KOL3"},
        {"name": "Kolkata Store 4", "code": "STORE-KOL4"},
    ],
    "Kashmir": [
        {"name": "Kashmir Store 1", "code": "STORE-KAS1"},
        {"name": "Kashmir Store 2", "code": "STORE-KAS2"},
        {"name": "Kashmir Store 3", "code": "STORE-KAS3"},
        {"name": "Kashmir Store 4", "code": "STORE-KAS4"},
    ],
}


def seed_all():
    """Seed the entire database. Idempotent — skips if data already exists."""
    init_db()
    db = SessionLocal()

    try:
        # Check if already seeded
        if db.query(Region).count() > 0:
            print("[SEED] Database already seeded — skipping.")
            return

        print("[SEED] Seeding database...")

        # ── Regions ────────────────────────────────────────────────────────────
        regions = {}
        for name in ["Kolkata", "Kashmir"]:
            region = Region(name=name)
            db.add(region)
            db.flush()
            regions[name] = region
        print(f"  [OK] {len(regions)} regions created")

        # ── Warehouses ─────────────────────────────────────────────────────────
        warehouses = {}
        for region_name, region in regions.items():
            wh = Warehouse(
                name=f"Warehouse-{region_name}",
                region_id=region.id,
                capacity=1000.0,
                current_stock=500.0,
            )
            db.add(wh)
            db.flush()
            warehouses[region_name] = wh
        print(f"  [OK] {len(warehouses)} warehouses created")

        # ── Products ───────────────────────────────────────────────────────────
        products = []
        for p_data in DEFAULT_PRODUCTS:
            product = Product(**p_data)
            db.add(product)
            db.flush()
            products.append(product)
        print(f"  [OK] {len(products)} products created")

        # ── Stores + Users + Inventory ─────────────────────────────────────────
        store_count = 0
        user_count = 0
        inventory_count = 0

        for region_name, store_defs in STORES.items():
            region = regions[region_name]
            for store_def in store_defs:
                # Create store
                store = Store(
                    name=store_def["name"],
                    store_code=store_def["code"],
                    region_id=region.id,
                )
                db.add(store)
                db.flush()
                store_count += 1

                # Derive short suffix: STORE-KOL1 → kol1
                suffix = store_def["code"].split("-")[1].lower()

                # Create Store Manager
                sm = User(
                    user_id=f"sm_{suffix}",
                    password="password123",
                    display_name=f"Store Manager {store_def['code']}",
                    role="store_manager",
                    store_id=store.id,
                    region_id=region.id,
                )
                db.add(sm)
                user_count += 1

                # Create Sales Person
                sp = User(
                    user_id=f"sp_{suffix}",
                    password="password123",
                    display_name=f"Sales Person {store_def['code']}",
                    role="sales_person",
                    store_id=store.id,
                    region_id=region.id,
                )
                db.add(sp)
                user_count += 1

                # Create inventory for each product
                for product in products:
                    inv = StoreInventory(
                        store_id=store.id,
                        product_id=product.id,
                        quantity=100.0,
                    )
                    db.add(inv)
                    inventory_count += 1

        print(f"  [OK] {store_count} stores created")
        print(f"  [OK] {user_count} store staff created")
        print(f"  [OK] {inventory_count} inventory rows created")

        # ── Regional Managers ──────────────────────────────────────────────────
        for region_name, region in regions.items():
            rm = User(
                user_id=f"rm_{region_name.lower()}",
                password="password123",
                display_name=f"Regional Manager {region_name}",
                role="regional_manager",
                store_id=None,
                region_id=region.id,
            )
            db.add(rm)
            user_count += 1
        print(f"  [OK] 2 regional managers created")

        db.commit()
        print(f"[SEED] Done -- {user_count} total users seeded.")
        print("[SEED] Default credentials: password = 'password123'")
        print("[SEED] User IDs: sm_kol1..sm_kas4, sp_kol1..sp_kas4, rm_kolkata, rm_kashmir")

    except Exception as exc:
        db.rollback()
        print(f"[SEED] Error: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_all()
