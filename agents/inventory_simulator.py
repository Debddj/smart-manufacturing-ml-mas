"""
agents/inventory_simulator.py

Background inventory simulation for the Supply Chain MAS.
Runs as a daemon thread, periodically:
  - Simulates random sales (decrements inventory)
  - Simulates restocking (increments inventory when low)
  - AUTO-PROCUREMENT: When any product drops to ≤40 units,
    sends a procurement email with PDF invoice to the manufacturer.

This creates realistic, dynamic inventory fluctuations visible
on both Store Manager and Regional Manager dashboards.
"""

from __future__ import annotations

import random
import threading
import time
import logging
import uuid
from typing import Optional, Set, Tuple

logger = logging.getLogger("InventorySimulator")

# Threshold at which auto-procurement email is triggered
PROCUREMENT_THRESHOLD = 40.0


class InventorySimulator:
    """
    Continuously simulates inventory changes across all stores.

    Parameters:
        interval_seconds: Time between simulation ticks.
        sales_per_tick:   Number of random sales to simulate per tick.
        restock_threshold: Restock when stock falls below this quantity.
        restock_amount:   Units added when restocking.
    """

    def __init__(
        self,
        interval_seconds: float = 15.0,
        sales_per_tick: int = 3,
        restock_threshold: float = 30.0,
        restock_amount: float = 80.0,
    ) -> None:
        self.interval = interval_seconds
        self.sales_per_tick = sales_per_tick
        self.restock_threshold = restock_threshold
        self.restock_amount = restock_amount
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Track (store_id, product_id) pairs that have already triggered
        # a procurement email — avoids spamming on every tick
        self._emailed_items: Set[Tuple[int, int]] = set()
        self._email_lock = threading.Lock()

    def start(self) -> None:
        """Start the simulator in a background daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("[SIMULATOR] Inventory simulator started (interval=%ss)", self.interval)

    def stop(self) -> None:
        """Stop the simulator."""
        self._running = False
        logger.info("[SIMULATOR] Inventory simulator stopped.")

    def _loop(self) -> None:
        """Main simulation loop."""
        # Wait a bit for DB to be fully seeded on first startup
        time.sleep(5.0)

        while self._running:
            try:
                self._tick()
            except Exception as exc:
                logger.error("[SIMULATOR] Tick error: %s", exc, exc_info=True)
            time.sleep(self.interval)

    def _tick(self) -> None:
        """
        One simulation tick: auto-procurement alerts + opportunistic restocking.

        Random sale simulation has been intentionally REMOVED.
        All inventory deductions now come exclusively from real shop orders
        placed by salespersons via process_order_deduction(), ensuring that
        'Today's Sales' on the store manager dashboard only shows genuine orders.
        """
        from db.database import SessionLocal
        from db.models import StoreInventory, StockAlert
        import datetime as _dt

        LOW_STOCK_THRESHOLD = 20.0
        CRITICAL_THRESHOLD  = 5.0

        db = SessionLocal()
        try:
            # Get all inventory records
            all_inv = db.query(StoreInventory).all()
            if not all_inv:
                return

            # ── Auto-procurement email trigger (≤40 units) ─────────────
            low_items = [
                inv for inv in all_inv
                if inv.quantity <= PROCUREMENT_THRESHOLD
                and (inv.store_id, inv.product_id) not in self._emailed_items
            ]
            if low_items:
                self._trigger_procurement_emails(low_items, db)

            # NOTE: Auto-restocking has been REMOVED.
            # Inventory only changes via real shop orders
            # (process_order_deduction), keeping the dashboard accurate.

            db.commit()

        except Exception as exc:
            db.rollback()
            logger.error("[SIMULATOR] DB error: %s", exc)
        finally:
            db.close()

    def _trigger_procurement_emails(self, low_items, db) -> None:
        """
        Send procurement emails for inventory items that have hit ≤40 units.
        Each (store, product) pair only triggers ONE email until restocked.
        Runs email sending in a separate thread to avoid blocking the tick.
        """
        from db.models import Store, Product

        # Collect details before spawning thread
        email_batch = []
        for inv in low_items:
            key = (inv.store_id, inv.product_id)
            with self._email_lock:
                if key in self._emailed_items:
                    continue
                self._emailed_items.add(key)

            # Fetch related store and product info
            store = db.query(Store).filter_by(id=inv.store_id).first()
            product = db.query(Product).filter_by(id=inv.product_id).first()
            if not store or not product:
                continue

            email_batch.append({
                "store_name": store.name,
                "store_code": store.store_code,
                "product_name": product.name,
                "sku": product.sku,
                "category": product.category,
                "unit_price": product.unit_price,
                "current_stock": inv.quantity,
                "reorder_qty": 100.0,  # standard reorder quantity
            })

        if email_batch:
            # Send emails in background thread to avoid blocking simulation
            threading.Thread(
                target=self._send_procurement_batch,
                args=(email_batch,),
                daemon=True,
            ).start()

    # ── Order-driven inventory deduction ─────────────────────────────────────

    @staticmethod
    def process_order_deduction(store_id: int, items: list, system_user_id: int = 1, order_id: str = "") -> list:
        """
        Deduct ordered quantities from a specific store's DB inventory.

        Called by the order pipeline whenever a real shop order is placed.
        Unlike the random simulation tick, this is deterministic and directly
        tied to actual cart items.

        Args:
            store_id:       The store whose inventory to deduct from.
            items:          List of {"sku": str, "qty": int/float} dicts.
            system_user_id: User ID to record on Sale rows (defaults to 1 / first manager).

        Returns:
            List of update dicts: [{product_id, product_name, sku, old_qty, new_qty, alert}]
        """
        from db.database import SessionLocal
        from db.models import StoreInventory, Product, Sale, StockAlert, User, Store
        import datetime as _dt
        from automations.store_logger import log_store_sale, log_store_inventory

        LOW_STOCK_THRESHOLD = 20.0
        CRITICAL_THRESHOLD  = 5.0

        db = SessionLocal()
        updates = []
        try:
            # Resolve the system user (fallback to first active user for store)
            user = db.query(User).filter(
                User.store_id == store_id,
                User.is_active == True,
            ).first()
            sold_by_id = user.id if user else system_user_id

            # Fetch store code once for CSV filenames
            store_obj = db.query(Store).filter(Store.id == store_id).first()
            store_code = store_obj.store_code if store_obj else f"STORE-{store_id}"

            for item in items:
                sku = item.get("sku", "")
                qty = float(item.get("qty", 1))

                # Look up product by SKU
                product = db.query(Product).filter(Product.sku == sku).first()
                if not product:
                    logger.warning("[ORDER-DEDUCT] SKU not found: %s", sku)
                    continue

                # Look up store inventory row
                inv = db.query(StoreInventory).filter(
                    StoreInventory.store_id == store_id,
                    StoreInventory.product_id == product.id,
                ).first()
                if not inv:
                    logger.warning(
                        "[ORDER-DEDUCT] No inventory row for store_id=%s, sku=%s", store_id, sku
                    )
                    continue

                old_qty = inv.quantity
                actual_sold = min(qty, old_qty)   # can't sell more than was in stock
                # Deduct — floor at 0
                inv.quantity = max(0.0, inv.quantity - qty)
                inv.last_updated = _dt.datetime.utcnow()

                # Record as a Sale
                sale = Sale(
                    store_id=store_id,
                    product_id=product.id,
                    quantity=actual_sold,
                    sale_price=product.unit_price * actual_sold,
                    sold_by=sold_by_id,
                )
                db.add(sale)

                # Alert logic
                alert_type = None
                if inv.quantity <= CRITICAL_THRESHOLD:
                    alert_type = "out_of_stock"
                elif inv.quantity <= LOW_STOCK_THRESHOLD:
                    # Only if no unresolved alert already exists
                    existing = db.query(StockAlert).filter(
                        StockAlert.store_id == store_id,
                        StockAlert.product_id == product.id,
                        StockAlert.alert_type == "low_stock",
                        StockAlert.is_resolved == False,
                    ).first()
                    if not existing:
                        alert_type = "low_stock"

                if alert_type:
                    alert = StockAlert(
                        store_id=store_id,
                        product_id=product.id,
                        alert_type=alert_type,
                        threshold=CRITICAL_THRESHOLD if alert_type == "out_of_stock" else LOW_STOCK_THRESHOLD,
                        current_level=inv.quantity,
                    )
                    db.add(alert)

                updates.append({
                    "product_id":   product.id,
                    "product_name": product.name,
                    "sku":          sku,
                    "old_qty":      round(old_qty, 1),
                    "new_qty":      round(inv.quantity, 1),
                    "change":       -round(actual_sold, 1),
                    "alert":        alert_type,
                })

                logger.info(
                    "[ORDER-DEDUCT] store=%s  sku=%s  %s → %s (-%s)",
                    store_id, sku, round(old_qty, 1), round(inv.quantity, 1), round(actual_sold, 1),
                )

                # ── Write per-store CSV logs ──────────────────────────────────
                # Sales log — one entry per product line in the order
                log_store_sale(
                    store_id=store_id,
                    store_code=store_code,
                    product_name=product.name,
                    sku=sku,
                    qty=actual_sold,
                    unit_price=product.unit_price,
                    order_id=order_id or f"ORD-STORE-{store_id}",
                )
                # Inventory log — reflects the new stock level
                log_store_inventory(
                    store_id=store_id,
                    store_code=store_code,
                    product_name=product.name,
                    sku=sku,
                    previous_qty=old_qty,
                    change_qty=-actual_sold,
                    remaining_qty=round(inv.quantity, 1),
                    alert=alert_type,
                )
                # ─────────────────────────────────────────────────────────────

            db.commit()

        except Exception as exc:
            db.rollback()
            logger.error("[ORDER-DEDUCT] DB error: %s", exc)
        finally:
            db.close()

        return updates

    @staticmethod
    def _send_procurement_batch(batch: list) -> None:
        """
        Send procurement emails for a batch of low-stock items.
        Each item gets its own email with PDF invoice attached.
        """
        try:
            from automations.email_sender import EmailSender
            sender = EmailSender()

            for item in batch:
                order_id = f"AUTO-{uuid.uuid4().hex[:8].upper()}"
                reorder_qty = item["reorder_qty"]
                cost = reorder_qty * item["unit_price"]

                print(
                    f"[AUTO-PROCUREMENT] {item['store_code']} | "
                    f"{item['product_name']} ({item['sku']}) dropped to "
                    f"{item['current_stock']:.0f} units -- sending procurement email",
                    flush=True,
                )

                success = sender.send_procurement_email(
                    order_id=order_id,
                    supplier_name=f"Manufacturer ({item['category']})",
                    units=reorder_qty,
                    cost=cost,
                    delivery_days=5,
                )

                if success:
                    print(
                        f"[AUTO-PROCUREMENT] Email sent for {item['sku']} | "
                        f"Order: {order_id} | Qty: {reorder_qty:.0f} | "
                        f"Cost: Rs{cost:,.2f}",
                        flush=True,
                    )
                else:
                    print(
                        f"[AUTO-PROCUREMENT] Email failed for {item['sku']} "
                        f"(check SENDER_EMAIL / SENDER_PASSWORD in .env)",
                        flush=True,
                    )

                # Small delay between emails to avoid rate-limiting
                time.sleep(1.0)

        except Exception as exc:
            print(f"[AUTO-PROCUREMENT] [ERROR] Batch email failed: {exc}", flush=True)


# Singleton instance
_simulator: Optional[InventorySimulator] = None


def get_simulator() -> InventorySimulator:
    """Get or create the global simulator instance."""
    global _simulator
    if _simulator is None:
        _simulator = InventorySimulator(
            interval_seconds=15.0,   # every 15 seconds
            sales_per_tick=3,        # 3 random sales per tick
            restock_threshold=30.0,  # restock when below 30
            restock_amount=80.0,     # add ~80 units
        )
    return _simulator
