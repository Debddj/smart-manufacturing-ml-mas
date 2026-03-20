"""
Bakes all training data into a standalone dashboard HTML file.

After training, simulation_runner calls this once. The output is a
fully self-contained HTML file at outputs/dashboard.html that opens
in any browser without a server.
"""

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
    """
    Generates outputs/dashboard.html with training data embedded as a
    JavaScript constant (window.DASHBOARD_DATA).

    Parameters
    ----------
    sample_size   : number of last-episode steps to include in time-series charts.
    open_browser  : if True, opens the dashboard in the default browser on completion.
    """

    os.makedirs(os.path.dirname(output_html), exist_ok=True)

    # ── Count disruption types ────────────────────────────────────────────────
    type_counts: dict[str, int] = {}
    for event in disruption_log:
        t = event["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    # ── Trim time-series to sample_size ──────────────────────────────────────
    n = min(sample_size, len(demand_history))

    def _round_list(lst, dp=2):
        return [round(float(v), dp) for v in lst[-n:]]

    data = {
        "meta": {
            "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "episodes":   len(episode_rewards),
            "model":      "Q-Learning (tabular)",
            "dataset":    "demand.csv",
        },
        "final_metrics": {k: round(float(v), 4) for k, v in final_metrics.items()},
        "resilience_metrics": {k: round(float(v), 4) for k, v in resilience_metrics.items()},
        "episode_rewards":    [round(float(r), 1) for r in episode_rewards],
        "episode_fill_rates": [round(float(f), 4) for f in episode_fill_rates],
        "episode_avg_delays": [round(float(d), 4) for d in episode_avg_delays],
        "demand_sample":      _round_list(demand_history),
        "satisfied_sample":   _round_list(satisfied_history),
        "inventory_sample":   _round_list(inventory_history),
        "prod_cost_sample":   _round_list(production_costs),
        "hold_cost_sample":   _round_list(holding_costs),
        "delay_cost_sample":  _round_list(delay_costs),
        "disruption_log":     disruption_log,
        "disruption_type_counts": type_counts,
    }

    # ── Read the template and inject data ────────────────────────────────────
    template_path = Path(__file__).parent / "dashboard.html"
    if not template_path.exists():
        print(f"  Warning: dashboard template not found at {template_path}")
        print("  Writing data-only JSON to outputs/metrics.json instead.")
        with open("outputs/metrics.json", "w") as f:
            json.dump(data, f, indent=2)
        return

    template = template_path.read_text(encoding="utf-8")
    injection = f"window.DASHBOARD_DATA = {json.dumps(data, indent=2)};"
    output = template.replace("/* __INJECT_DATA__ */", injection)

    with open(output_html, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"\nDashboard exported → {output_html}")

    if open_browser:
        webbrowser.open(f"file://{os.path.abspath(output_html)}")
        print("  Opening in browser...") 