import csv
import os
from datetime import datetime

script_dir = os.path.dirname(os.path.abspath(__file__))
log_file = os.path.join(script_dir, 'warehouse_log.csv')

with open(log_file, 'a', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow([
        datetime.now().isoformat(),
        "TestAgent",
        "Test Action",
        "WH-A → WH-B",
        100,
        "Test",
        "ord-test"
    ])
print("CSV updated")