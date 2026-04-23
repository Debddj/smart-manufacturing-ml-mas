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
        Product(
            sku="SKU-WIDGET-A", name="Industrial Precision Widget A",
            category="electronics", base_demand=85.0, unit_price=24.99,
            lead_time=1, warehouse_node="A",
            description="High-precision industrial component for manufacturing lines.",
            common_questions=["Is it RoHS compliant?", "What tolerances does it support?"],
            compatible_accessories=["SKU-MOUNT-01", "SKU-CABLE-03"],
            substitutes=["SKU-WIDGET-B"], tags=["precision", "industrial", "electronics"],
        ),
        Product(
            sku="SKU-SENSOR-PRO", name="Smart IoT Sensor Module Pro",
            category="sensors", base_demand=62.0, unit_price=89.50,
            lead_time=2, warehouse_node="B",
            description="Multi-protocol IoT sensor with edge AI capability.",
            common_questions=["Which protocols does it support?", "IP rating?"],
            compatible_accessories=["SKU-HUB-01"],
            tags=["iot", "sensor", "ai-enabled"],
        ),
        Product(
            sku="SKU-ACTUATOR-X", name="Linear Actuator X-Series",
            category="mechanical", base_demand=40.0, unit_price=156.00,
            lead_time=3, warehouse_node="C",
            description="Heavy-duty linear actuator for automated assembly systems.",
            common_questions=["Max load capacity?", "Stroke length options?"],
            substitutes=["SKU-ACTUATOR-Y"], tags=["mechanical", "automation"],
        ),
        Product(
            sku="SKU-CTRL-UNIT", name="PLC Control Unit v4",
            category="control-systems", base_demand=22.0, unit_price=445.00,
            lead_time=5, warehouse_node="A",
            description="Programmable logic controller with modbus/ethernet support.",
            tags=["plc", "control", "automation", "industrial"],
        ),
        Product(
            sku="SKU-PWR-SUPPLY", name="48V Industrial Power Supply",
            category="power", base_demand=55.0, unit_price=67.99,
            lead_time=1, warehouse_node="A",
            description="DIN-rail mount 48V/20A industrial power supply unit.",
            tags=["power", "din-rail", "industrial"],
        ),
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