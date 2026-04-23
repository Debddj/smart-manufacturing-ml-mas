"""
agents/inter_store_agent.py

Manages logistics and communication for inter-store stock transfers.
Listens to TRANSFER_REQUEST and TRANSFER_APPROVED events.
"""

from __future__ import annotations

import logging
from communication.message_bus import MessageBus, MessageType, Priority
from db.database import SessionLocal
from db.models import TransferRequest

logger = logging.getLogger("InterStoreAgent")

class InterStoreAgent:
    def __init__(self, bus: MessageBus):
        self.bus = bus
        self.bus.subscribe(MessageType.TRANSFER_REQUEST, self.on_transfer_request)
        self.bus.subscribe(MessageType.TRANSFER_APPROVED, self.on_transfer_approved)
        logger.info("InterStoreAgent initialized.")

    def on_transfer_request(self, payload: dict) -> None:
        """
        Triggered when a store requests a transfer from another store.
        """
        transfer_id = payload.get("transfer_id")
        logger.info(f"InterStoreAgent processing new transfer request {transfer_id}.")
        # In a fully automated system, this agent might automatically approve transfers
        # if the source store has excess stock based on ML predictions.

    def on_transfer_approved(self, payload: dict) -> None:
        """
        Triggered when a transfer is approved.
        Could integrate with LogisticsAgent to actually move the physical goods.
        """
        transfer_id = payload.get("transfer_id")
        logger.info(f"InterStoreAgent coordinating logistics for approved transfer {transfer_id}.")
        
        db = SessionLocal()
        try:
            from db.models import Product
            transfer = db.query(TransferRequest).filter(TransferRequest.id == transfer_id).first()
            if transfer:
                product = db.query(Product).filter(Product.id == transfer.product_id).first()
                sku = f"PROD-{transfer.product_id}"
                if product:
                    sku = product.name.upper().replace(" ", "-")

                # Trigger physical logistics simulation
                self.bus.publish(
                    "SIMULATE_FULFILLMENT",
                    sender="InterStoreAgent",
                    payload={
                        "order_id": f"TRANSFER-{transfer_id}",
                        "items": [{"sku": sku, "qty": transfer.quantity}]
                    }
                )
        except Exception as e:
            logger.error(f"Error in InterStoreAgent: {e}")
        finally:
            db.close()
