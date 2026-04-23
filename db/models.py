"""
db/models.py — SQLAlchemy ORM models for the Multi-Store Retail Management System.

Models:
    User             — login credentials + role assignment
    Region           — geographic region (Kolkata / Kashmir)
    Store            — retail store belonging to a region
    Product          — shared product catalog (5 products)
    StoreInventory   — per-store stock levels for each product
    Sale             — individual sale transactions
    TransferRequest  — inter-store stock transfer requests
    Warehouse        — regional warehouse
    WarehouseTransfer— cross-region warehouse transfers
    StockAlert       — automated low-stock / high-demand alerts
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, Enum
)
from sqlalchemy.orm import relationship
from db.database import Base


# ── User ───────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(String(50), unique=True, nullable=False, index=True)  # login ID
    password     = Column(String(100), nullable=False)                          # plain text
    display_name = Column(String(100), nullable=False)
    role         = Column(String(30), nullable=False)  # store_manager | sales_person | regional_manager
    store_id     = Column(Integer, ForeignKey("stores.id"), nullable=True)
    region_id    = Column(Integer, ForeignKey("regions.id"), nullable=True)
    is_active    = Column(Boolean, default=True)
    created_at   = Column(DateTime, default=datetime.datetime.utcnow)

    store  = relationship("Store",  back_populates="staff")
    region = relationship("Region", back_populates="managers")
    sales  = relationship("Sale",   back_populates="sold_by_user")

    def to_dict(self):
        return {
            "id":           self.id,
            "user_id":      self.user_id,
            "display_name": self.display_name,
            "role":         self.role,
            "store_id":     self.store_id,
            "region_id":    self.region_id,
            "is_active":    self.is_active,
        }


# ── Region ─────────────────────────────────────────────────────────────────────

class Region(Base):
    __tablename__ = "regions"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(50), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    stores    = relationship("Store",     back_populates="region")
    managers  = relationship("User",      back_populates="region")
    warehouse = relationship("Warehouse", back_populates="region", uselist=False)


# ── Store ──────────────────────────────────────────────────────────────────────

class Store(Base):
    __tablename__ = "stores"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(100), nullable=False)
    store_code = Column(String(20), unique=True, nullable=False)
    region_id  = Column(Integer, ForeignKey("regions.id"), nullable=False)
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    region    = relationship("Region",         back_populates="stores")
    staff     = relationship("User",           back_populates="store")
    inventory = relationship("StoreInventory", back_populates="store")
    sales     = relationship("Sale",           back_populates="store")
    alerts    = relationship("StockAlert",     back_populates="store")


# ── Product ────────────────────────────────────────────────────────────────────

class Product(Base):
    __tablename__ = "products"

    id          = Column(Integer, primary_key=True, index=True)
    sku         = Column(String(30), unique=True, nullable=False)
    name        = Column(String(150), nullable=False)
    category    = Column(String(50), nullable=False)
    unit_price  = Column(Float, nullable=False)
    base_demand = Column(Float, default=50.0)
    description = Column(Text, default="")
    is_active   = Column(Boolean, default=True)

    store_inventory = relationship("StoreInventory", back_populates="product")
    sales           = relationship("Sale",           back_populates="product")


# ── StoreInventory ─────────────────────────────────────────────────────────────

class StoreInventory(Base):
    __tablename__ = "store_inventory"

    id           = Column(Integer, primary_key=True, index=True)
    store_id     = Column(Integer, ForeignKey("stores.id"), nullable=False)
    product_id   = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity     = Column(Float, default=100.0)
    last_updated = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    store   = relationship("Store",   back_populates="inventory")
    product = relationship("Product", back_populates="store_inventory")

    def to_dict(self):
        return {
            "id":           self.id,
            "store_id":     self.store_id,
            "product_id":   self.product_id,
            "product_sku":  self.product.sku if self.product else None,
            "product_name": self.product.name if self.product else None,
            "quantity":     self.quantity,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }


# ── Sale ───────────────────────────────────────────────────────────────────────

class Sale(Base):
    __tablename__ = "sales"

    id         = Column(Integer, primary_key=True, index=True)
    store_id   = Column(Integer, ForeignKey("stores.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity   = Column(Float, nullable=False)
    sale_price = Column(Float, nullable=False)
    sold_by    = Column(Integer, ForeignKey("users.id"), nullable=False)
    sold_at    = Column(DateTime, default=datetime.datetime.utcnow)

    store        = relationship("Store",   back_populates="sales")
    product      = relationship("Product", back_populates="sales")
    sold_by_user = relationship("User",    back_populates="sales")

    def to_dict(self):
        return {
            "id":           self.id,
            "store_id":     self.store_id,
            "product_id":   self.product_id,
            "product_name": self.product.name if self.product else None,
            "quantity":     self.quantity,
            "sale_price":   self.sale_price,
            "sold_by":      self.sold_by,
            "sold_at":      self.sold_at.isoformat() if self.sold_at else None,
        }


# ── TransferRequest ────────────────────────────────────────────────────────────

class TransferRequest(Base):
    __tablename__ = "transfer_requests"

    id            = Column(Integer, primary_key=True, index=True)
    from_store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    to_store_id   = Column(Integer, ForeignKey("stores.id"), nullable=False)
    product_id    = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity      = Column(Float, nullable=False)
    status        = Column(String(20), default="pending")  # pending | approved | completed | rejected
    requested_by  = Column(Integer, ForeignKey("users.id"), nullable=False)
    approved_by   = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at    = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at  = Column(DateTime, nullable=True)

    from_store = relationship("Store", foreign_keys=[from_store_id])
    to_store   = relationship("Store", foreign_keys=[to_store_id])
    product    = relationship("Product")
    requester  = relationship("User", foreign_keys=[requested_by])
    approver   = relationship("User", foreign_keys=[approved_by])

    def to_dict(self):
        return {
            "id":              self.id,
            "from_store_id":   self.from_store_id,
            "from_store_name": self.from_store.name if self.from_store else None,
            "to_store_id":     self.to_store_id,
            "to_store_name":   self.to_store.name if self.to_store else None,
            "product_id":      self.product_id,
            "product_name":    self.product.name if self.product else None,
            "quantity":        self.quantity,
            "status":          self.status,
            "requested_by":    self.requested_by,
            "created_at":      self.created_at.isoformat() if self.created_at else None,
        }


# ── Warehouse ──────────────────────────────────────────────────────────────────

class Warehouse(Base):
    __tablename__ = "warehouses"

    id            = Column(Integer, primary_key=True, index=True)
    name          = Column(String(100), nullable=False)
    region_id     = Column(Integer, ForeignKey("regions.id"), nullable=False, unique=True)
    capacity      = Column(Float, default=1000.0)
    current_stock = Column(Float, default=500.0)
    created_at    = Column(DateTime, default=datetime.datetime.utcnow)

    region = relationship("Region", back_populates="warehouse")


# ── WarehouseTransfer ──────────────────────────────────────────────────────────

class WarehouseTransfer(Base):
    __tablename__ = "warehouse_transfers"

    id                = Column(Integer, primary_key=True, index=True)
    from_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    to_warehouse_id   = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    units             = Column(Float, nullable=False)
    reason            = Column(String(200), default="")
    transfer_type     = Column(String(30), default="cross_region")  # cross_region | rebalance
    status            = Column(String(20), default="pending")       # pending | in_transit | completed
    created_at        = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at      = Column(DateTime, nullable=True)

    from_warehouse = relationship("Warehouse", foreign_keys=[from_warehouse_id])
    to_warehouse   = relationship("Warehouse", foreign_keys=[to_warehouse_id])


# ── StockAlert ─────────────────────────────────────────────────────────────────

class StockAlert(Base):
    __tablename__ = "stock_alerts"

    id            = Column(Integer, primary_key=True, index=True)
    store_id      = Column(Integer, ForeignKey("stores.id"), nullable=False)
    product_id    = Column(Integer, ForeignKey("products.id"), nullable=False)
    alert_type    = Column(String(30), nullable=False)  # low_stock | high_demand | out_of_stock
    threshold     = Column(Float, nullable=True)
    current_level = Column(Float, nullable=True)
    is_resolved   = Column(Boolean, default=False)
    created_at    = Column(DateTime, default=datetime.datetime.utcnow)
    resolved_at   = Column(DateTime, nullable=True)

    store   = relationship("Store", back_populates="alerts")
    product = relationship("Product")

    def to_dict(self):
        return {
            "id":            self.id,
            "store_id":      self.store_id,
            "product_id":    self.product_id,
            "product_name":  self.product.name if self.product else None,
            "alert_type":    self.alert_type,
            "threshold":     self.threshold,
            "current_level": self.current_level,
            "is_resolved":   self.is_resolved,
            "created_at":    self.created_at.isoformat() if self.created_at else None,
        }
