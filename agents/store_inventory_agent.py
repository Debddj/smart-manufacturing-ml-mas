"""
agents/store_inventory_agent.py — Replaces the human Inventory Manager role.

Automated inventory management for individual stores:
- Monitors stock levels per store in real-time.
- Subscribes to SALE_RECORDED events from SalesSyncAgent.
- Triggers LOW_STOCK_ALERT and HIGH_DEMAND_ALERT via message_bus.
- Auto-requests restocking from the regional warehouse when stock is critical.
"""

from __future__ import annotations

import logging
from sqlalchemy.orm import Session
from communication.message_bus import MessageBus, MessageType, Priority
from db.database import SessionLocal
from db.models import StoreInventory, Store, StockAlert, Product

logger = logging.getLogger("StoreInventoryAgent")

class StoreInventoryAgent:
    def __init__(self, bus: MessageBus):
        self.bus = bus
        self.bus.subscribe(MessageType.SALE_RECORDED, self.on_sale_recorded)
        logger.info("StoreInventoryAgent initialized.")

    def on_sale_recorded(self, payload: dict) -> None:
        """
        Triggered when a sale happens.
        Evaluates stock levels and triggers alerts/restocks if necessary.
        """
        store_id = payload.get("store_id")
        product_id = payload.get("product_id")
        quantity_sold = payload.get("quantity")

        if not store_id or not product_id:
            return

        db: Session = SessionLocal()
        try:
            inv = db.query(StoreInventory).filter(
                StoreInventory.store_id == store_id,
                StoreInventory.product_id == product_id
            ).first()

            if not inv:
                return

            product = db.query(Product).filter(Product.id == product_id).first()
            if not product:
                return

            # Check thresholds
            reorder_point = product.base_demand * 3.0  # e.g., 3 days of base demand
            critical_point = product.base_demand * 1.0

            if inv.quantity <= critical_point:
                self._trigger_alert(db, store_id, product_id, "out_of_stock", critical_point, inv.quantity)
                self._request_restock(store_id, product_id, product.base_demand * 5) # Restock 5 days worth
            elif inv.quantity <= reorder_point:
                self._trigger_alert(db, store_id, product_id, "low_stock", reorder_point, inv.quantity)
                self._request_restock(store_id, product_id, product.base_demand * 3)

            # High demand check (simplified heuristic: if sold qty > base_demand in one sale)
            if quantity_sold > product.base_demand:
                self._trigger_alert(db, store_id, product_id, "high_demand", product.base_demand, quantity_sold)

            db.commit()
        except Exception as e:
            logger.error(f"Error in StoreInventoryAgent: {e}")
            db.rollback()
        finally:
            db.close()

    def _trigger_alert(self, db: Session, store_id: int, product_id: int, alert_type: str, threshold: float, current_level: float):
        # Check if active alert already exists to prevent spam
        existing = db.query(StockAlert).filter(
            StockAlert.store_id == store_id,
            StockAlert.product_id == product_id,
            StockAlert.alert_type == alert_type,
            StockAlert.is_resolved == False
        ).first()

        if not existing:
            alert = StockAlert(
                store_id=store_id,
                product_id=product_id,
                alert_type=alert_type,
                threshold=threshold,
                current_level=current_level
            )
            db.add(alert)
            # The actual commit happens in the caller

            # Broadcast alert to message bus
            self.bus.publish(
                message_type=MessageType.STOCK_ALERT,
                sender="StoreInventoryAgent",
                payload={"store_id": store_id, "product_id": product_id, "alert_type": alert_type},
                priority=Priority.WARNING
            )

    def _request_restock(self, store_id: int, product_id: int, quantity: float):
        self.bus.publish(
            message_type=MessageType.RESTOCK_REQUEST,
            sender="StoreInventoryAgent",
            payload={"store_id": store_id, "product_id": product_id, "quantity": quantity},
            priority=Priority.ACTION
        )
