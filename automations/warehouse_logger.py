"""
automations/warehouse_logger.py

CSV warehouse transfer logger for Supply Chain MAS.
Appends transfer and dispatch events to a local warehouse_log.csv file.

Triggers:
    1. InventoryAgent._execute() — after warehouse routing decision (Action="Transfer")
    2. LogisticsAgent._execute() — after loading goods (Action="Dispatch")
"""

from __future__ import annotations

import csv
import datetime
import os
from pathlib import Path

# ── Path to log file (project root level) ────────────────────────────────────
LOG_FILE = Path(__file__).parent.parent / "warehouse_log.csv"

CSV_HEADERS = [
    "Timestamp",
    "Agent",
    "Action",
    "From",
    "To",
    "Units",
    "Context",
    "OrderID",
]


def _ensure_csv_exists() -> None:
    """Create warehouse_log.csv with headers if it does not already exist."""
    if not LOG_FILE.exists():
        with open(LOG_FILE, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)


def log_warehouse_transfer(
    agent_name: str,
    from_wh: str,
    to_wh: str,
    units: float,
    context: str,
    order_id: str,
    action: str = "Transfer",
) -> bool:
    """
    Append one row to warehouse_log.csv recording a warehouse transfer or dispatch.

    Args:
        agent_name: Name of the calling agent (e.g. "InventoryAgent").
        from_wh:    Source warehouse identifier (e.g. "Warehouse B").
        to_wh:      Destination warehouse identifier (e.g. "Warehouse A").
        units:      Number of units moved.
        context:    Environment context string (e.g. "Winter" or "Summer").
        order_id:   The order this transfer belongs to.
        action:     Row label — "Transfer" (inventory routing) or "Dispatch" (logistics).

    Returns:
        True if the row was written successfully, False otherwise.
    """
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"[LOG] [{ts}] {agent_name} | {action}: {from_wh} → {to_wh} | "
        f"Units: {units} | Context: {context} | Order: {order_id}"
    )

    try:
        _ensure_csv_exists()
        with open(LOG_FILE, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([ts, agent_name, action, from_wh, to_wh, units, context, order_id])
        return True
    except Exception as exc:
        print(f"[LOG] [ERROR] Failed to write warehouse log: {exc}")
        return False
