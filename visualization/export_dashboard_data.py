import json
import os
import webbrowser
from datetime import datetime
from pathlib import Path


def export_dashboard_data(
    episode_rewards:    list,
    episode_fill_rates: list,
    episode_avg_delays: list,
    demand_history:     list,
    satisfied_history:  list,
    inventory_history:  list,
    production_costs:   list,
    holding_costs:      list,
    delay_costs:        list,
    disruption_log:     list,
    final_metrics:      dict,
    resilience_metrics: dict,
    sample_size:        int = 600,
    output_html:        str = "outputs/dashboard.html",
    open_browser:       bool = True,
):
    os.makedirs(os.path.dirname(output_html), exist_ok=True)

    type_counts: dict[str, int] = {}
    for event in disruption_log:
        t = event["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    n = min(sample_size, len(demand_history))

    def _round_list(lst, dp=2):
        return [round(float(v), dp) for v in lst[-n:]]

    # Cap disruption log to 200 entries for the dashboard table
    log_capped = disruption_log[:200] if len(disruption_log) > 200 else disruption_log

    data = {
        "meta": {
            "trained_at":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "episodes":        len(episode_rewards),
            "model":           "Q-Learning (tabular)",
            "dataset":         "demand.csv",
            "total_events":    len(disruption_log),
        },
        "final_metrics":     {k: round(float(v), 4) for k, v in final_metrics.items()},
        "resilience_metrics":{k: round(float(v), 4) for k, v in resilience_metrics.items()},
        "episode_rewards":   [round(float(r), 1) for r in episode_rewards],
        "episode_fill_rates":[round(float(f), 4) for f in episode_fill_rates],
        "episode_avg_delays":[round(float(d), 4) for d in episode_avg_delays],
        "demand_sample":     _round_list(demand_history),
        "satisfied_sample":  _round_list(satisfied_history),
        "inventory_sample":  _round_list(inventory_history),
        "prod_cost_sample":  _round_list(production_costs),
        "hold_cost_sample":  _round_list(holding_costs),
        "delay_cost_sample": _round_list(delay_costs),
        "disruption_log":    log_capped,
        "disruption_type_counts": type_counts,
    }

    template_path = Path(__file__).parent / "dashboard.html"
    if not template_path.exists():
        print(f"  Warning: dashboard.html template not found at {template_path}")
        json_path = "outputs/metrics.json"
        with open(json_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  Fallback: data written to {json_path}")
        return

    template  = template_path.read_text(encoding="utf-8")
    injection = f"window.DASHBOARD_DATA = {json.dumps(data, indent=2)};"
    output    = template.replace("/* __INJECT_DATA__ */", injection)

    with open(output_html, "w", encoding="utf-8") as f:
        f.write(output)

    abs_path = os.path.abspath(output_html)
    url      = "file:///" + abs_path.replace("\\", "/")   # Windows-safe

    print(f"\nDashboard exported → {output_html}")
    print(f"  Open in browser:  {url}")

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass  # silently skip if browser launch fails