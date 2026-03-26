"""
Exports training data into dashboard.html template.

FIXES APPLIED:
    1. Added optional 'rl_meta' parameter — simulation_runner.py passes
       this dict (agent_type, n_bins, actions, etc.) and the original
       signature didn't accept it, causing TypeError at runtime.
    2. rl_meta is included in the injected JSON so the dashboard can
       display which agent type and configuration was used.
"""

import json
import os
import webbrowser
from datetime import datetime
from pathlib import Path


def export_dashboard_data(
    episode_rewards:     list,
    episode_fill_rates:  list,
    episode_avg_delays:  list,
    demand_history:      list,
    satisfied_history:   list,
    inventory_history:   list,
    production_costs:    list,
    holding_costs:       list,
    delay_costs:         list,
    disruption_log:      list,
    final_metrics:       dict,
    resilience_metrics:  dict,
    scenario_comparison: dict,
    agent_logs:          list,
    sla:                 dict,
    rl_meta:             dict  = None,   # FIX: added — was causing TypeError
    sample_size:         int   = 600,
    output_html:         str   = "outputs/dashboard.html",
    open_browser:        bool  = True,
):
    os.makedirs(os.path.dirname(output_html), exist_ok=True)

    type_counts: dict = {}
    for event in disruption_log:
        t = event["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    n = min(sample_size, len(demand_history))

    def _r(lst, dp=2):
        return [round(float(v), dp) for v in lst[-n:]]

    log_capped = disruption_log[:200] if len(disruption_log) > 200 else disruption_log

    # Prioritise CRITICAL + DISRUPTION entries, sample the rest
    priority_logs = [l for l in agent_logs if l.get("severity") in ("CRITICAL", "ALERT", "DISRUPTION")]
    other_logs    = [l for l in agent_logs if l.get("severity") not in ("CRITICAL", "ALERT", "DISRUPTION")]
    combined_logs = (priority_logs + other_logs)[:500]

    fill_sla  = sla.get("fill_rate", 0.90)
    delay_sla = sla.get("avg_delay",  5.0)

    data = {
        "meta": {
            "trained_at":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "episodes":          len(episode_rewards),
            "model":             (rl_meta or {}).get("agent_type", "Q-Learning (tabular 20×20)"),
            "dataset":           "demand.csv",
            "total_events":      len(disruption_log),
            "total_log_entries": len(combined_logs),
            "multi_warehouse":   (rl_meta or {}).get("multi_warehouse", False),
        },
        "sla": {"fill_rate": fill_sla, "avg_delay": delay_sla},
        "sla_compliance": {
            "fill_rate": {
                "value":  round(float(final_metrics.get("Fill Rate", 0)), 4),
                "target": fill_sla,
                "pass":   float(final_metrics.get("Fill Rate", 0)) >= fill_sla,
            },
            "avg_delay": {
                "value":  round(float(final_metrics.get("Avg Delay", 999)), 2),
                "target": delay_sla,
                "pass":   float(final_metrics.get("Avg Delay", 999)) <= delay_sla,
            },
        },
        "final_metrics":      {k: round(float(v), 4) for k, v in final_metrics.items()},
        "resilience_metrics": {k: round(float(v), 4) for k, v in resilience_metrics.items()},
        "scenario_comparison": scenario_comparison,
        "rl_meta":             rl_meta or {},          # FIX: included in JSON output
        "episode_rewards":    [round(float(r), 1) for r in episode_rewards],
        "episode_fill_rates": [round(float(f), 4) for f in episode_fill_rates],
        "episode_avg_delays": [round(float(d), 4) for d in episode_avg_delays],
        "demand_sample":      _r(demand_history),
        "satisfied_sample":   _r(satisfied_history),
        "inventory_sample":   _r(inventory_history),
        "prod_cost_sample":   _r(production_costs),
        "hold_cost_sample":   _r(holding_costs),
        "delay_cost_sample":  _r(delay_costs),
        "disruption_log":     log_capped,
        "disruption_type_counts": type_counts,
        "agent_logs":         combined_logs,
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

    # Auto-copy to repo root for GitHub Pages
    import shutil
    index_path = Path(__file__).parent.parent / "index.html"
    shutil.copy(output_html, index_path)
    print(f"  GitHub Pages index updated → {index_path}")

    abs_path = os.path.abspath(output_html)
    url      = "file:///" + abs_path.replace("\\", "/")

    print(f"\nDashboard exported → {output_html}")
    print(f"  Open in browser:  {url}")

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass