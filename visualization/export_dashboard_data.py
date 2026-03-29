"""
Exports training data into dashboard.html template.

FIXES:
    1. 'agent_logs' key renamed to 'agent_events' — dashboard JS reads D.agent_events
    2. 'total_events' renamed to 'total_disruption_events' — dashboard reads D.meta.total_disruption_events
    3. 'total_log_entries' renamed to 'total_agent_events' — dashboard reads D.meta.total_agent_events
    4. rl_meta values injected into meta block so D.meta.model reflects actual agent
    5. sla_compliance added to exported data for dashboard KPI badges
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
    rl_meta:             dict  = None,
    sample_size:         int   = 600,
    output_html:         str   = "outputs/dashboard.html",
    open_browser:        bool  = True,
):
    os.makedirs(os.path.dirname(output_html), exist_ok=True)

    # Count disruption type occurrences across all episodes
    type_counts: dict = {}
    for event in disruption_log:
        t = event["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    n = min(sample_size, len(demand_history))

    def _r(lst, dp=2):
        return [round(float(v), dp) for v in lst[-n:]]

    log_capped = disruption_log[:200] if len(disruption_log) > 200 else disruption_log

    # Prioritise ALERT + RESOLVED entries, sample the rest for variety
    priority_logs = [l for l in agent_logs if l.get("severity") in ("ALERT", "RESOLVED", "WARNING")]
    action_logs   = [l for l in agent_logs if l.get("severity") == "ACTION"]
    info_logs     = [l for l in agent_logs if l.get("severity") == "INFO"]
    combined_logs = (priority_logs + action_logs + info_logs)[:500]

    fill_sla  = sla.get("fill_rate", 0.90)
    delay_sla = sla.get("avg_delay",  5.0)

    fill_val  = float(final_metrics.get("Fill Rate", 0))
    delay_val = float(final_metrics.get("Avg Delay", 999))

    meta_block = {
        "trained_at":            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "episodes":              len(episode_rewards),
        # FIX: use actual agent type from rl_meta
        "model":                 (rl_meta or {}).get("agent_type", "Q-Learning (tabular 20×20)"),
        "dataset":               "demand.csv",
        # FIX: was "total_events" — dashboard reads D.meta.total_disruption_events
        "total_disruption_events": len(disruption_log),
        # FIX: was "total_log_entries" — dashboard reads D.meta.total_agent_events
        "total_agent_events":    len(combined_logs),
        "multi_warehouse":       (rl_meta or {}).get("multi_warehouse", False),
    }

    data = {
        "meta": meta_block,
        "sla":  {"fill_rate": fill_sla, "avg_delay": delay_sla},
        "sla_compliance": {
            "fill_rate": {
                "value":  round(fill_val,  4),
                "target": fill_sla,
                "pass":   fill_val >= fill_sla,
            },
            "avg_delay": {
                "value":  round(delay_val, 2),
                "target": delay_sla,
                "pass":   delay_val <= delay_sla,
            },
        },
        "rl_meta":             rl_meta or {},
        "final_metrics":       {k: round(float(v), 4) for k, v in final_metrics.items()},
        "resilience_metrics":  {k: round(float(v), 4) for k, v in resilience_metrics.items()},
        "scenario_comparison": scenario_comparison,
        "episode_rewards":     [round(float(r), 1) for r in episode_rewards],
        "episode_fill_rates":  [round(float(f), 4) for f in episode_fill_rates],
        "episode_avg_delays":  [round(float(d), 4) for d in episode_avg_delays],
        "demand_sample":       _r(demand_history),
        "satisfied_sample":    _r(satisfied_history),
        "inventory_sample":    _r(inventory_history),
        "prod_cost_sample":    _r(production_costs),
        "hold_cost_sample":    _r(holding_costs),
        "delay_cost_sample":   _r(delay_costs),
        "disruption_log":      log_capped,
        "disruption_type_counts": type_counts,
        # FIX: was "agent_logs" — dashboard JS reads D.agent_events
        "agent_events":        combined_logs,
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