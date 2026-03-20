import numpy as np


def compute_metrics(costs, demands, satisfied):
    total_cost  = sum(costs)
    fill_rate   = sum(satisfied) / (sum(demands) + 1e-9)
    delays      = [max(0, d - s) for d, s in zip(demands, satisfied)]
    avg_delay   = float(np.mean(delays))
    throughput  = sum(satisfied)

    return {
        "Total Cost": total_cost,
        "Fill Rate":  fill_rate,
        "Avg Delay":  avg_delay,
        "Throughput": throughput,
    }


def compute_resilience_metrics(
    fill_rates_per_step: list[float],
    disruption_log:      list[dict],
    steps_total:         int,
) -> dict:
    """
    Measure how well the RL policy holds up under and recovers from disruptions.

    Metrics returned:
      resilience_score      — fill_during_disruption / fill_normal  (1.0 = unaffected)
      avg_recovery_steps    — mean steps to return to ≥0.85 fill rate after each event
      disruption_rate       — fraction of total steps that had an active disruption
      fill_during_disruption — mean per-step fill rate while disrupted
      fill_normal            — mean per-step fill rate when no disruption is active
    """
    if not disruption_log or not fill_rates_per_step:
        return {
            "resilience_score":       1.0,
            "avg_recovery_steps":     0.0,
            "disruption_rate":        0.0,
            "fill_during_disruption": float(np.mean(fill_rates_per_step)) if fill_rates_per_step else 1.0,
            "fill_normal":            float(np.mean(fill_rates_per_step)) if fill_rates_per_step else 1.0,
        }

    # Build a set of steps that were disrupted
    disrupted_steps: set[int] = set()
    for event in disruption_log:
        for s in range(event["step"], event["step"] + event["duration"]):
            if s < steps_total:
                disrupted_steps.add(s)

    disruption_rate = len(disrupted_steps) / max(steps_total, 1)

    fill_disrupted = [
        fill_rates_per_step[s]
        for s in disrupted_steps
        if s < len(fill_rates_per_step)
    ]
    fill_normal = [
        fill_rates_per_step[s]
        for s in range(steps_total)
        if s not in disrupted_steps and s < len(fill_rates_per_step)
    ]

    avg_disrupted = float(np.mean(fill_disrupted)) if fill_disrupted else 1.0
    avg_normal    = float(np.mean(fill_normal))    if fill_normal    else 1.0

    # Recovery time: steps after each disruption ends until fill rate ≥ 0.85
    recovery_times = []
    RECOVERY_THRESHOLD = 0.85
    SEARCH_WINDOW = 60  # steps to look ahead

    for event in disruption_log:
        end_step = event["step"] + event["duration"]
        recovered = False
        for t in range(end_step, min(end_step + SEARCH_WINDOW, len(fill_rates_per_step))):
            if fill_rates_per_step[t] >= RECOVERY_THRESHOLD:
                recovery_times.append(t - end_step)
                recovered = True
                break
        if not recovered:
            recovery_times.append(SEARCH_WINDOW)  # did not recover within window

    resilience_score = avg_disrupted / max(avg_normal, 1e-9)

    return {
        "resilience_score":       round(resilience_score, 4),
        "avg_recovery_steps":     round(float(np.mean(recovery_times)), 2) if recovery_times else 0.0,
        "disruption_rate":        round(disruption_rate, 4),
        "fill_during_disruption": round(avg_disrupted, 4),
        "fill_normal":            round(avg_normal, 4),
    } 