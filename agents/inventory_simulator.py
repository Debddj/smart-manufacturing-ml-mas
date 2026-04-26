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
        """One simulation tick: random sales + low-stock procurement + restocking."""
        from db.database import SessionLocal
        from db.models import StoreInventory, Store, Product

        db = SessionLocal()
        try:
            # Get all inventory records
            all_inv = db.query(StoreInventory).all()
            if not all_inv:
                return

            # ── Simulate sales (decrement) ─────────────────────────────
            sale_candidates = [inv for inv in all_inv if inv.quantity > 5]
            if sale_candidates:
                items_to_sell = random.sample(
                    sale_candidates,
                    min(self.sales_per_tick, len(sale_candidates)),
                )
                for inv in items_to_sell:
                    max_sell = min(15, int(inv.quantity * 0.15))
                    sell_qty = random.randint(1, max(1, max_sell))
                    inv.quantity = max(0, inv.quantity - sell_qty)

            # ── Auto-procurement email trigger (≤40 units) ─────────────
            # Check all inventory items; if any has hit the threshold
            # and we haven't already emailed about it, fire a
            # procurement email to the manufacturer.
            low_items = [
                inv for inv in all_inv
                if inv.quantity <= PROCUREMENT_THRESHOLD
                and (inv.store_id, inv.product_id) not in self._emailed_items
            ]
            if low_items:
                self._trigger_procurement_emails(low_items, db)

            # ── Simulate restocking (increment) ───────────────────────
            # Restock items that have fallen below the restock threshold
            low_stock = [inv for inv in all_inv if inv.quantity < self.restock_threshold]
            for inv in low_stock:
                # ~30% chance of restock per tick (gradual, not instant)
                if random.random() < 0.3:
                    restock_qty = self.restock_amount + random.uniform(-20, 30)
                    inv.quantity += round(restock_qty, 1)
                    # Clear the email flag so it can re-trigger if it drops again
                    with self._email_lock:
                        self._emailed_items.discard((inv.store_id, inv.product_id))

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
