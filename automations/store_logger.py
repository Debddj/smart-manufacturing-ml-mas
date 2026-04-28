"""
automations/store_logger.py

Per-store CSV logging for the Supply Chain MAS.

Two log files are maintained per store:
  - store_{store_code}_sales_log.csv    — every order placed via the shop catalogue
  - store_{store_code}_inventory_log.csv — every time stock changes (deduction or restock)

These files live next to warehouse_log.csv in the project root so they are easy
to inspect alongside the existing logs.

Called by:
    agents/inventory_simulator.InventorySimulator.process_order_deduction()
"""

from __future__ import annotations

import csv
import datetime
from pathlib import Path

# ── Root log directory (same level as warehouse_log.csv) ─────────────────────
LOG_DIR = Path(__file__).parent.parent
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── Column schemas ────────────────────────────────────────────────────────────

SALES_HEADERS = [
    "Timestamp",
    "OrderID",
    "StoreID",
    "StoreCode",
    "ProductName",
    "SKU",
    "QuantityOrdered",
    "UnitPrice",
    "TotalValue",
]

INVENTORY_HEADERS = [
    "Timestamp",
    "OrderID",
    "StoreID",
    "StoreCode",
    "ProductName",
    "SKU",
    "PreviousQty",
    "ChangeQty",
    "RemainingQty",
    "Alert",
]


def _sales_path(store_code: str) -> Path:
    return LOG_DIR / f"store_{store_code}_sales_log.csv"


def _inventory_path(store_code: str) -> Path:
    return LOG_DIR / f"store_{store_code}_inventory_log.csv"


def _ensure_csv(path: Path, headers: list[str]) -> None:
    """Create the CSV file with headers if it does not already exist."""
    if not path.exists():
        with open(path, mode="w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(headers)


# ── Public API ────────────────────────────────────────────────────────────────

def log_store_sale(
    *,
    store_id: int,
    store_code: str,
    product_name: str,
    sku: str,
    qty: float,
    unit_price: float,
    order_id: str,
) -> bool:
    """
    Append one sale record to store_{store_code}_sales_log.csv.

    Called once per product line-item when a shop order is placed.

    Returns True on success, False on error (never raises).
    """
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = _sales_path(store_code)
    try:
        _ensure_csv(path, SALES_HEADERS)
        with open(path, mode="a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                ts,
                order_id,
                store_id,
                store_code,
                product_name,
                sku,
                round(qty, 2),
                round(unit_price, 2),
                round(qty * unit_price, 2),
            ])
        print(
            f"[STORE-LOG] SALE  | {store_code} | {sku} | qty={qty} | order={order_id}",
            flush=True,
        )
        return True
    except Exception as exc:
        print(f"[STORE-LOG] ERROR writing sales log for {store_code}: {exc}", flush=True)
        return False


def log_store_inventory(
    *,
    store_id: int,
    store_code: str,
    product_name: str,
    sku: str,
    previous_qty: float,
    change_qty: float,        # negative means deduction, positive means restock
    remaining_qty: float,
    alert: str | None = None,
    order_id: str = "",
) -> bool:
    """
    Append one inventory-change record to store_{store_code}_inventory_log.csv.

    Called every time the stock level changes (order deduction or simulator restock).

    Returns True on success, False on error (never raises).
    """
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = _inventory_path(store_code)
    try:
        _ensure_csv(path, INVENTORY_HEADERS)
        with open(path, mode="a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                ts,
                order_id,
                store_id,
                store_code,
                product_name,
                sku,
                round(previous_qty, 2),
                round(change_qty, 2),
                round(remaining_qty, 2),
                alert or "",
            ])
        print(
            f"[STORE-LOG] INV   | {store_code} | {sku} | "
            f"{previous_qty} → {remaining_qty} (Δ{change_qty:+.1f}) | alert={alert}",
            flush=True,
        )
        return True
    except Exception as exc:
        print(f"[STORE-LOG] ERROR writing inventory log for {store_code}: {exc}", flush=True)
        return False
