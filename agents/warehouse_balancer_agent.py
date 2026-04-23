"""
agents/warehouse_balancer_agent.py

Monitors the regional warehouses and balances stock between them using the existing
RL/DQN demand prediction models.

Listens to RESTOCK_REQUEST from StoreInventoryAgent.
"""

from __future__ import annotations

import logging
from communication.message_bus import MessageBus, MessageType, Priority
from db.database import SessionLocal
from db.models import Warehouse, Store, Product
from forecasting.demand_engine import predict_demand
from rl.dqn_agent import DQNAgent

logger = logging.getLogger("WarehouseBalancerAgent")

class WarehouseBalancerAgent:
    def __init__(self, bus: MessageBus):
        self.bus = bus
        self.bus.subscribe(MessageType.RESTOCK_REQUEST, self.on_restock_request)
        self.dqn = DQNAgent()
        try:
            self.dqn.load("outputs/dqn_weights.pt")
        except Exception:
            logger.warning("No DQN weights found, using untrained model.")
        logger.info("WarehouseBalancerAgent initialized.")

    def on_restock_request(self, payload: dict) -> None:
        """
        Triggered when a store requests a restock from its regional warehouse.
        payload is a dict with: store_id, product_id, quantity.
        """
        store_id = payload.get("store_id")
        product_id = payload.get("product_id")
        quantity = payload.get("quantity")

        if not store_id or not product_id or not quantity:
            logger.warning(f"Incomplete RESTOCK_REQUEST payload: {payload}")
            return

        db = SessionLocal()
        try:
            store = db.query(Store).filter(Store.id == store_id).first()
            if not store:
                logger.error(f"Store {store_id} not found.")
                return

            warehouse = db.query(Warehouse).filter(Warehouse.region_id == store.region_id).first()
            if not warehouse:
                logger.error(f"No warehouse found for region {store.region_id}")
                return

            product = db.query(Product).filter(Product.id == product_id).first()
            sku = f"PROD-{product_id}"
            if product:
                sku = product.name.upper().replace(" ", "-")

            logger.info(f"Warehouse {warehouse.name} processing restock of {quantity} units of product {product_id} for store {store.name}.")

            # 1. Trigger the legacy MAS _run_order pipeline via MessageBus
            self.bus.publish(
                message_type="SIMULATE_FULFILLMENT",
                sender="WarehouseBalancerAgent",
                payload={
                    "order_id": f"RESTOCK-{store.store_code}",
                    "items": [{"sku": sku, "qty": quantity}]
                }
            )

            # 2. Check if warehouse is running low and needs cross-region transfer
            if warehouse.current_stock < quantity * 2:
                logger.warning(f"Warehouse {warehouse.name} stock low ({warehouse.current_stock}). Using RL model to predict demand.")

                # predict_demand() returns a dict like {"item_name": "high"/"medium"/"low"}
                demand_predictions = predict_demand()
                pred_qty = 50.0  # default fallback
                if demand_predictions:
                    # Count items predicted as "high" demand to scale procurement
                    high_demand_count = sum(1 for v in demand_predictions.values() if v == "high")
                    pred_qty = 50.0 + high_demand_count * 20.0

                action_idx = self.dqn.choose_action(warehouse.current_stock, pred_qty)
                recommended_procurement = self.dqn.actions[action_idx]
                logger.warning(f"DQN Agent recommends procuring {recommended_procurement} units for {warehouse.name}.")

                # Dispatch procurement event
                self.bus.publish(
                    message_type="PROCUREMENT_REQUEST",
                    sender="WarehouseBalancerAgent",
                    payload={"warehouse_id": warehouse.id, "quantity": recommended_procurement}
                )
        except Exception as e:
            logger.error(f"Error in WarehouseBalancerAgent: {e}", exc_info=True)
        finally:
            db.close()
