"""
agents/sales_sync_agent.py

Syncs sales data across the system.
When a sale is recorded via the API, the API decrements inventory and publishes to the WebSocket.
This agent can be used to aggregate sales data, update ML demand forecasting inputs,
and publish SALE_RECORDED events to the message bus for the StoreInventoryAgent.
"""

from __future__ import annotations

import logging
from communication.message_bus import MessageBus, MessageType, Priority
from db.database import SessionLocal
from db.models import Sale

logger = logging.getLogger("SalesSyncAgent")

class SalesSyncAgent:
    def __init__(self, bus: MessageBus):
        self.bus = bus
        logger.info("SalesSyncAgent initialized.")

    def record_sale_event(self, sale_id: int):
        """
        Called when a sale is successfully recorded in the DB.
        Fetches the sale and publishes a SALE_RECORDED event.
        """
        db = SessionLocal()
        try:
            sale = db.query(Sale).filter(Sale.id == sale_id).first()
            if sale:
                self.bus.publish(
                    message_type=MessageType.SALE_RECORDED,
                    sender="SalesSyncAgent",
                    payload={
                        "sale_id": sale.id,
                        "store_id": sale.store_id,
                        "product_id": sale.product_id,
                        "quantity": sale.quantity,
                        "sale_price": sale.sale_price
                    },
                    priority=Priority.INFO
                )
                logger.info(f"Published SALE_RECORDED for sale {sale_id}")
        except Exception as e:
            logger.error(f"Error in SalesSyncAgent: {e}")
        finally:
            db.close()
