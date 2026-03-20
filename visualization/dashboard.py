def show_summary(metrics):

    print("\n=== DASHBOARD ===")
    for k, v in metrics.items():
        print(f"{k}: {round(v,2)}") 