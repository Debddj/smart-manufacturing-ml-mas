import os
import pandas as pd

def load_demand_data():
    file_path = os.path.join(os.path.dirname(__file__), "..", "demand_log.csv")
    columns = ["timestamp", "item_name", "quantity"]
    
    if not os.path.exists(file_path):
        return pd.DataFrame(columns=columns)
        
    try:
        df = pd.read_csv(file_path)
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
