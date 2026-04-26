"""
UCP Product Catalog — Dynamic product registry for the ML-MAS platform.

Implements UCP Discovery capability:
  - Products are registered with rich attributes (UCP Merchant Center style)
  - Agents query /profile to discover available capabilities
  - Real-time inventory is pulled from the WarehouseNetwork
  - Supports common product questions, accessories, substitutes (UCP attributes)

Usage:
    catalog = ProductCatalog()
    catalog.add_product(Product(
        sku="SKU-001", name="Industrial Widget A",
        category="electronics", base_demand=85.0,
        unit_price=24.99, lead_time=1,
    ))
    results = catalog.search("industrial widget")
    product  = catalog.get("SKU-001")
    inventory = catalog.get_inventory("SKU-001")
"""

from __future__ import annotations
import uuid
import time
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass
class Product:
    """
    UCP-compliant product record.

    Attributes mirror UCP Merchant Center data attributes:
      name, description, category, sku, unit_price,
      base_demand, lead_time, warehouse_node,
      common_questions, compatible_accessories, substitutes
    """
    name:            str
    category:        str
    unit_price:      float
    base_demand:     float          # average daily demand (units)
    sku:             str  = field(default_factory=lambda: f"SKU-{uuid.uuid4().hex[:8].upper()}")
    description:     str  = ""
    lead_time:       int  = 1       # days
    warehouse_node:  str  = "A"     # primary warehouse node
    min_order_qty:   int  = 1
    max_order_qty:   int  = 500
    weight_kg:       float = 0.5
    common_questions: List[str] = field(default_factory=list)
    compatible_accessories: List[str] = field(default_factory=list)
    substitutes:     List[str] = field(default_factory=list)
    tags:            List[str] = field(default_factory=list)
    # Runtime state
    current_inventory: float = 100.0
    created_at:      float = field(default_factory=time.time)
    is_active:       bool  = True

    def to_dict(self) -> dict:
        return asdict(self)

    def to_ucp_listing(self) -> dict:
        """Returns UCP-compliant product listing format."""
        return {
            "id":          self.sku,
            "name":        self.name,
            "description": self.description,
            "category":    self.category,
            "price":       {"amount": self.unit_price, "currency": "INR"},
            "inventory":   {"available": int(self.current_inventory), "unit": "units"},
            "fulfillment": {
                "lead_time_days": self.lead_time,
                "warehouse":      self.warehouse_node,
                "min_qty":        self.min_order_qty,
                "max_qty":        self.max_order_qty,
            },
            "attributes": {
                "weight_kg":    self.weight_kg,
                "tags":         self.tags,
                "common_questions": self.common_questions,
                "compatible_accessories": self.compatible_accessories,
                "substitutes":  self.substitutes,
            },
            "agent_context": {
                "base_daily_demand": self.base_demand,
                "reorder_recommended": self.current_inventory < self.base_demand * 3,
            },
        }


class ProductCatalog:
    """
    Dynamic product registry — the UCP Discovery endpoint.

    Supports:
      - Adding/removing products at runtime (dynamic, not dataset-bound)
      - Full-text search across name, category, description, tags
      - Real-time inventory sync with WarehouseNetwork
      - UCP capability profile generation
    """

    DEFAULT_PRODUCTS = [
        # Raw Materials
        Product(sku="CRSC-1500", name="Cold-Rolled Steel Coils", category="Raw Materials", base_demand=85.0, unit_price=2840.00, lead_time=6, warehouse_node="A",
                description="High-strength HSLA steel coils, 1.5mm gauge.", tags=["steel", "raw-material", "coils"]),
        Product(sku="AL61-T6", name="6061-T6 Aluminium Sheet", category="Raw Materials", base_demand=62.0, unit_price=1250.00, lead_time=4, warehouse_node="A",
                description="Aerospace-grade aluminium alloy, 3mm thickness.", tags=["aluminium", "raw-material", "aerospace"]),
        Product(sku="ECW-25", name="Electrolytic Copper Wire", category="Raw Materials", base_demand=70.0, unit_price=780.00, lead_time=3, warehouse_node="A",
                description="99.9% pure copper conductor, 2.5mm AWG.", tags=["copper", "wire", "raw-material"]),
        Product(sku="CFP-240", name="Carbon Fiber Prepreg", category="Raw Materials", base_demand=22.0, unit_price=4200.00, lead_time=10, warehouse_node="B",
                description="Unidirectional carbon fiber, 240 GSM.", tags=["carbon-fiber", "composite", "raw-material"]),
        Product(sku="PA66-GF30", name="Polyamide 66 Pellets (GF30)", category="Raw Materials", base_demand=90.0, unit_price=380.00, lead_time=2, warehouse_node="A",
                description="Glass-filled PA66 pellets, 30% GF.", tags=["polymer", "pellets", "injection-moulding"]),
        Product(sku="BGT-25", name="Borosilicate Glass Tubes", category="Raw Materials", base_demand=40.0, unit_price=290.00, lead_time=7, warehouse_node="B",
                description="Precision borosilicate tubing, OD 25mm.", tags=["glass", "tubes", "raw-material"]),
        # Components
        Product(sku="SRV-2K", name="AC Servo Motor 2.0 kW", category="Components", base_demand=45.0, unit_price=1640.00, lead_time=6, warehouse_node="A",
                description="Closed-loop AC servo, 2000W, IP65.", tags=["servo", "motor", "cnc"]),
        Product(sku="PLC-S71200", name="PLC Controller S7-1200", category="Components", base_demand=28.0, unit_price=2180.00, lead_time=8, warehouse_node="A",
                description="Compact PLC, 14 DI/10 DO, PROFINET enabled.", tags=["plc", "control", "automation"]),
        Product(sku="IPS-M18", name="Inductive Proximity Sensor", category="Components", base_demand=100.0, unit_price=95.00, lead_time=1, warehouse_node="A",
                description="NPN NO, M18 housing, 8mm sensing range.", tags=["sensor", "proximity", "industrial"]),
        Product(sku="PCB-4L", name="4-Layer Industrial PCB", category="Components", base_demand=75.0, unit_price=220.00, lead_time=5, warehouse_node="B",
                description="FR4 substrate, 1oz copper, ENIG finish.", tags=["pcb", "electronics", "components"]),
        Product(sku="HYD-50K", name="Hydraulic Cylinder 50 kN", category="Components", base_demand=14.0, unit_price=3100.00, lead_time=12, warehouse_node="C",
                description="Double-acting, 50kN force, 300mm stroke.", tags=["hydraulic", "cylinder", "mechanical"]),
        Product(sku="ACB-7208", name="Angular Contact Bearing 7208", category="Components", base_demand=80.0, unit_price=145.00, lead_time=2, warehouse_node="A",
                description="40x80x18mm angular contact ball bearing.", tags=["bearing", "mechanical", "precision"]),
        Product(sku="RTD-PT100", name="Pt100 RTD Temperature Probe", category="Components", base_demand=50.0, unit_price=185.00, lead_time=4, warehouse_node="B",
                description="Class A resistance temperature detector.", tags=["sensor", "temperature", "rtd"]),
        Product(sku="PSU-24V10", name="24 VDC Power Supply 10 A", category="Components", base_demand=55.0, unit_price=165.00, lead_time=2, warehouse_node="A",
                description="DIN-rail mount SMPS, 24VDC / 10A output.", tags=["power", "din-rail", "industrial"]),
        # Assemblies
        Product(sku="ARM-6AX", name="6-Axis Robotic Arm Module", category="Assemblies", base_demand=5.0, unit_price=28500.00, lead_time=18, warehouse_node="C",
                description="Industrial robot, 6kg payload, 900mm reach.", tags=["robot", "arm", "automation"]),
        Product(sku="SPD-7K5", name="CNC Spindle Unit 7.5 kW", category="Assemblies", base_demand=8.0, unit_price=9800.00, lead_time=14, warehouse_node="C",
                description="High-speed CNC spindle, 7.5kW, 24000 RPM.", tags=["spindle", "cnc", "machining"]),
        Product(sku="CVR-3M", name="Modular Conveyor Belt - 3 m", category="Assemblies", base_demand=12.0, unit_price=6400.00, lead_time=12, warehouse_node="C",
                description="Variable-speed belt conveyor, 80kg capacity.", tags=["conveyor", "belt", "logistics"]),
        Product(sku="WLD-MIG", name="Automated MIG Welding Head", category="Assemblies", base_demand=15.0, unit_price=4750.00, lead_time=10, warehouse_node="C",
                description="Torch assembly with wire feeder, gas solenoid.", tags=["welding", "mig", "automation"]),
        Product(sku="VIS-12M", name="Machine Vision Inspection Unit", category="Assemblies", base_demand=6.0, unit_price=11200.00, lead_time=16, warehouse_node="C",
                description="12MP colour camera, telecentric lens.", tags=["vision", "inspection", "quality"]),
        # Consumables
        Product(sku="INS-CNMG", name="Carbide Turning Inserts x10", category="Consumables", base_demand=120.0, unit_price=68.00, lead_time=1, warehouse_node="A",
                description="CNMG 120408 grade, PVD TiAlN coated.", tags=["insert", "carbide", "machining"]),
        Product(sku="LUB-VG46", name="Hydraulic Oil ISO VG 46 - 20L", category="Consumables", base_demand=100.0, unit_price=115.00, lead_time=1, warehouse_node="A",
                description="Anti-wear mineral hydraulic oil, 20-litre drum.", tags=["oil", "lubricant", "hydraulic"]),
        Product(sku="WIR-70S6", name="MIG Wire ER70S-6 - 15 kg", category="Consumables", base_demand=85.0, unit_price=92.00, lead_time=1, warehouse_node="A",
                description="AWS ER70S-6 copper-coated mild steel wire.", tags=["wire", "welding", "consumable"]),
        Product(sku="FLT-HEPA", name="H14 HEPA Filter Set x4", category="Consumables", base_demand=60.0, unit_price=145.00, lead_time=4, warehouse_node="B",
                description="HEPA filter panels for CNC enclosures.", tags=["filter", "hepa", "consumable"]),
        Product(sku="GRD-ZA40", name="Zirconia Flap Discs x25", category="Consumables", base_demand=110.0, unit_price=48.00, lead_time=1, warehouse_node="A",
                description="125mm, 40 grit zirconia alumina flap discs.", tags=["grinding", "flap-disc", "consumable"]),
    ]

    def __init__(self, preload_defaults: bool = True):
        self._products: Dict[str, Product] = {}
        if preload_defaults:
            for p in self.DEFAULT_PRODUCTS:
                self._products[p.sku] = p

    def add_product(self, product: Product) -> str:
        """Register a new product. Returns the assigned SKU."""
        self._products[product.sku] = product
        return product.sku

    def remove_product(self, sku: str) -> bool:
        if sku in self._products:
            del self._products[sku]
            return True
        return False

    def get(self, sku: str) -> Optional[Product]:
        return self._products.get(sku)

    def all(self, active_only: bool = True) -> List[Product]:
        prods = list(self._products.values())
        return [p for p in prods if p.is_active] if active_only else prods

    def search(self, query: str, category: str = None, max_results: int = 20) -> List[Product]:
        """
        Full-text product search — UCP Discovery capability.
        Searches name, description, category, and tags.
        """
        q = query.lower().strip()
        results = []
        for p in self.all():
            if category and p.category.lower() != category.lower():
                continue
            score = 0
            if q in p.name.lower():       score += 3
            if q in p.description.lower(): score += 2
            if q in p.category.lower():    score += 2
            if any(q in t for t in p.tags): score += 1
            if any(q in cq.lower() for cq in p.common_questions): score += 1
            if score > 0:
                results.append((score, p))
        results.sort(key=lambda x: -x[0])
        return [p for _, p in results[:max_results]]

    def get_inventory(self, sku: str) -> dict:
        """Returns real-time inventory snapshot for a product."""
        p = self.get(sku)
        if not p:
            return {"error": f"Product {sku} not found"}
        return {
            "sku":       p.sku,
            "available": int(p.current_inventory),
            "status":    "in_stock" if p.current_inventory > p.base_demand
                         else "low_stock" if p.current_inventory > 0
                         else "out_of_stock",
            "reorder_point": round(p.base_demand * 3, 0),
        }

    def update_inventory(self, sku: str, quantity: float) -> bool:
        """Update inventory from warehouse agent signals."""
        p = self.get(sku)
        if p:
            p.current_inventory = max(0.0, quantity)
            return True
        return False

    def sync_from_warehouse(self, warehouse_snapshot: dict) -> int:
        """
        Sync inventory from a WarehouseNetwork snapshot.
        Returns number of products updated.
        """
        updated = 0
        for sku, product in self._products.items():
            node = warehouse_snapshot.get("nodes", {}).get(product.warehouse_node, {})
            if "inventory" in node:
                product.current_inventory = node["inventory"]
                updated += 1
        return updated

    def ucp_profile(self) -> dict:
        """
        Returns a UCP business profile (capability negotiation endpoint).
        Compatible with A2A and MCP discovery.
        """
        return {
            "ucp_version": "1.0",
            "business_id": "ml-mas-supply-chain",
            "business_name": "Smart Manufacturing ML-MAS Commerce",
            "capabilities": {
                "discovery": {
                    "enabled": True,
                    "search": True,
                    "real_time_inventory": True,
                    "category_browse": True,
                },
                "cart": {
                    "enabled": True,
                    "multi_item": True,
                    "quantity_update": True,
                    "save_for_later": True,
                },
                "checkout": {
                    "enabled": True,
                    "agentic": True,
                    "payment_methods": ["stripe", "purchase_order", "credit"],
                    "fulfillment_options": ["standard", "express", "bulk"],
                },
                "post_purchase": {
                    "enabled": True,
                    "order_tracking": True,
                    "returns": True,
                    "webhooks": True,
                },
            },
            "extensions": {
                "discounts": True,
                "loyalty": False,
                "subscriptions": False,
                "b2b_pricing": True,
            },
            "transport": ["REST", "MCP", "A2A"],
            "product_count": len(self._products),
        }

    def categories(self) -> List[str]:
        return sorted(list({p.category for p in self.all()}))

    def export_json(self) -> str:
        return json.dumps([p.to_dict() for p in self.all()], indent=2)