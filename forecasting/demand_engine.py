import os
import csv
import datetime
from pathlib import Path
import pandas as pd

_DEMAND_LOG = Path(__file__).parent.parent / "demand_log.csv"


def log_demand_items(cart_items: list, order_id: str = "") -> None:
    """
    Append each cart item to demand_log.csv.
    Creates the file with a header row if it does not already exist.

    Args:
        cart_items: list of {"sku": str, "qty": int} dicts
        order_id:   order identifier (optional — stored for traceability)
    """
    try:
        # Lazy import to avoid circular dependency
        from ucp.ucp_product_catalog import ProductCatalog
        _catalog = ProductCatalog()
    except Exception:
        _catalog = None

    write_header = not _DEMAND_LOG.exists()
    ts = datetime.datetime.now().isoformat()

    with open(_DEMAND_LOG, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["timestamp", "item_name", "quantity", "order_id"])
        for item in cart_items:
            sku = item.get("sku", "UNKNOWN")
            qty = item.get("qty", 1)
            if _catalog:
                product = _catalog.get(sku)
                name = product.name if product else sku
            else:
                name = sku
            writer.writerow([ts, name, qty, order_id])


def load_demand_data():
    columns = ["timestamp", "item_name", "quantity", "order_id"]

    if not _DEMAND_LOG.exists():
        return pd.DataFrame(columns=columns)

    try:
        df = pd.read_csv(_DEMAND_LOG)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        return df
    except Exception:
        return pd.DataFrame(columns=columns)

def aggregate_demand():
    df = load_demand_data()
    
    if df.empty:
        return {}
        
    aggregated = df.groupby("item_name")["quantity"].sum()
    return aggregated.to_dict()

def predict_demand():
    demand_dict = aggregate_demand()
    
    if not demand_dict:
        return {}
        
    sorted_items = sorted(demand_dict.items(), key=lambda x: x[1], reverse=True)
    num_items = len(sorted_items)
    
    predictions = {}
    for i, (item, _) in enumerate(sorted_items):
        if i < num_items / 3:
            predictions[item] = "high"
        elif i < 2 * num_items / 3:
            predictions[item] = "medium"
        else:
            predictions[item] = "low"
            
    return predictions
