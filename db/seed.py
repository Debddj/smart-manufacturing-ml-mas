"""
db/seed.py — Seed the database with initial data.

Creates:
    - 2 Regions: Kolkata, Kashmir
    - 2 Warehouses: Warehouse-Kolkata, Warehouse-Kashmir
    - 8 Stores: Store-KOL1..KOL4 (Kolkata), Store-KAS1..KAS4 (Kashmir)
    - 25 Products (from shop.html DEMO_PRODUCTS catalogue)
    - 200 StoreInventory rows (8 stores × 25 products, 100 units each)
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


# ── Product definitions (mirrors shop.html DEMO_PRODUCTS) ─────────────────────

DEFAULT_PRODUCTS = [
    # Raw Materials
    {"sku": "CRSC-1500",   "name": "Cold-Rolled Steel Coils",        "category": "Raw Materials",  "unit_price": 2840.00, "base_demand": 40.0,  "description": "High-strength HSLA steel coils, 1.5mm gauge. For stamping and roll-forming operations."},
    {"sku": "AL61-T6",     "name": "6061-T6 Aluminium Sheet",        "category": "Raw Materials",  "unit_price": 1250.00, "base_demand": 30.0,  "description": "Aerospace-grade aluminium alloy, 3mm thickness. Excellent machinability and corrosion resistance."},
    {"sku": "ECW-25",      "name": "Electrolytic Copper Wire",       "category": "Raw Materials",  "unit_price": 780.00,  "base_demand": 50.0,  "description": "99.9% pure copper conductor, 2.5mm AWG. Industrial grade for winding and cabling."},
    {"sku": "CFP-240",     "name": "Carbon Fiber Prepreg",           "category": "Raw Materials",  "unit_price": 4200.00, "base_demand": 8.0,   "description": "Unidirectional carbon fiber, 240 GSM. High modulus for structural composite applications."},
    {"sku": "PA66-GF30",   "name": "Polyamide 66 Pellets (GF30)",   "category": "Raw Materials",  "unit_price": 380.00,  "base_demand": 80.0,  "description": "Glass-filled PA66 pellets, 30% GF. High heat and chemical resistance for injection moulding."},
    {"sku": "BGT-25",      "name": "Borosilicate Glass Tubes",       "category": "Raw Materials",  "unit_price": 290.00,  "base_demand": 20.0,  "description": "Precision borosilicate tubing, OD 25mm. Low thermal expansion, high purity."},
    # Components
    {"sku": "SRV-2K",      "name": "AC Servo Motor 2.0 kW",          "category": "Components",     "unit_price": 1640.00, "base_demand": 15.0,  "description": "Closed-loop AC servo, 2000W, IP65. Integrated encoder for precise CNC motion control."},
    {"sku": "PLC-S71200",  "name": "PLC Controller S7-1200",         "category": "Components",     "unit_price": 2180.00, "base_demand": 10.0,  "description": "Compact PLC, 14 DI/10 DO, PROFINET enabled. Industry 4.0 ready, TIA Portal programmable."},
    {"sku": "IPS-M18",     "name": "Inductive Proximity Sensor",     "category": "Components",     "unit_price": 95.00,   "base_demand": 70.0,  "description": "NPN NO, M18 housing, 8mm sensing range. Stainless steel face, IP67 rated."},
    {"sku": "PCB-4L",      "name": "4-Layer Industrial PCB",         "category": "Components",     "unit_price": 220.00,  "base_demand": 45.0,  "description": "FR4 substrate, 1oz copper, ENIG finish. Designed for high-frequency switching circuits."},
    {"sku": "HYD-50K",     "name": "Hydraulic Cylinder 50 kN",       "category": "Components",     "unit_price": 3100.00, "base_demand": 5.0,   "description": "Double-acting, 50kN force, 300mm stroke. Honed barrel, hard chrome rod, BSPP ports."},
    {"sku": "ACB-7208",    "name": "Angular Contact Bearing 7208",   "category": "Components",     "unit_price": 145.00,  "base_demand": 60.0,  "description": "40x80x18mm angular contact ball bearing. Grease lubricated, C3 clearance, steel cage."},
    {"sku": "RTD-PT100",   "name": "Pt100 RTD Temperature Probe",    "category": "Components",     "unit_price": 185.00,  "base_demand": 25.0,  "description": "Class A resistance temperature detector, 6mm dia, 150mm insertion. -50 to +400 C."},
    {"sku": "PSU-24V10",   "name": "24 VDC Power Supply 10 A",       "category": "Components",     "unit_price": 165.00,  "base_demand": 35.0,  "description": "DIN-rail mount SMPS, 24VDC / 10A output. Wide input 85-264 VAC, CE/UL listed."},
    # Assemblies
    {"sku": "ARM-6AX",     "name": "6-Axis Robotic Arm Module",      "category": "Assemblies",     "unit_price": 28500.00,"base_demand": 2.0,   "description": "Industrial robot, 6kg payload, 900mm reach. Pre-calibrated with teach pendant and safety I/O."},
    {"sku": "SPD-7K5",     "name": "CNC Spindle Unit 7.5 kW",        "category": "Assemblies",     "unit_price": 9800.00, "base_demand": 3.0,   "description": "High-speed CNC spindle, 7.5kW, 24000 RPM. HSK-A63 tooling interface, liquid cooled."},
    {"sku": "CVR-3M",      "name": "Modular Conveyor Belt - 3 m",    "category": "Assemblies",     "unit_price": 6400.00, "base_demand": 4.0,   "description": "Variable-speed belt conveyor, 80kg capacity, plug-and-play. SEW inverter drive included."},
    {"sku": "WLD-MIG",     "name": "Automated MIG Welding Head",     "category": "Assemblies",     "unit_price": 4750.00, "base_demand": 5.0,   "description": "Torch assembly with wire feeder, gas solenoid and automated nozzle cleaning station."},
    {"sku": "VIS-12M",     "name": "Machine Vision Inspection Unit",  "category": "Assemblies",    "unit_price": 11200.00,"base_demand": 2.0,   "description": "12MP colour camera, telecentric lens, integrated LED ring light and onboard defect-detection PC."},
    # Consumables
    {"sku": "INS-CNMG",    "name": "Carbide Turning Inserts x10",    "category": "Consumables",    "unit_price": 68.00,   "base_demand": 120.0, "description": "CNMG 120408 grade, PVD TiAlN coated. For steel and stainless steels at medium to high feeds."},
    {"sku": "LUB-VG46",    "name": "Hydraulic Oil ISO VG 46 - 20L",  "category": "Consumables",    "unit_price": 115.00,  "base_demand": 90.0,  "description": "Anti-wear mineral hydraulic oil, 20-litre drum. Anti-foam, rust inhibited, zinc-based."},
    {"sku": "WIR-70S6",    "name": "MIG Wire ER70S-6 - 15 kg",       "category": "Consumables",    "unit_price": 92.00,   "base_demand": 70.0,  "description": "AWS ER70S-6 copper-coated mild steel wire, 0.9mm dia, 15kg spool. Excellent weld bead finish."},
    {"sku": "FLT-HEPA",    "name": "H14 HEPA Filter Set x4",         "category": "Consumables",    "unit_price": 145.00,  "base_demand": 40.0,  "description": "HEPA filter panels for CNC enclosures, 610x610mm, H14 class. Set of 4."},
    {"sku": "GRD-ZA40",    "name": "Zirconia Flap Discs x25",        "category": "Consumables",    "unit_price": 48.00,   "base_demand": 100.0, "description": "125mm, 40 grit zirconia alumina flap discs. Heavy stock removal on weld seams and steel."},
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
