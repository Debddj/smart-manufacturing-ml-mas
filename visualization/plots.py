import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import os

PLOT_DIR = "outputs/plots"
DISRUPTION_COLORS = {
    "supplier_failure":    "#E24B4A",
    "demand_surge":        "#BA7517",
    "logistics_breakdown": "#185FA5",
    "factory_slowdown":    "#534AB7",
}

def _savefig(name: str):
    os.makedirs(PLOT_DIR, exist_ok=True)
    path = f"{PLOT_DIR}/{name}.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


# ──────────────────────────────────────────────────────────────────────────────
# Existing plots (unchanged)
# ──────────────────────────────────────────────────────────────────────────────

def plot_learning_curve(rewards):
    plt.figure(figsize=(8, 4))
    plt.plot(rewards, color="#378ADD", linewidth=1.5)
    plt.title("RL Learning Curve")
    plt.xlabel("Episode")
    plt.ylabel("Total Reward")
    plt.grid(alpha=0.3)
    _savefig("learning_curve")


def plot_demand_vs_supply(demand, satisfied):
    plt.figure(figsize=(10, 4))
    plt.plot(demand,    label="Demand",    color="#378ADD", linewidth=0.8, alpha=0.8)
    plt.plot(satisfied, label="Satisfied", color="#1D9E75", linewidth=0.8, alpha=0.8)
    plt.legend()
    plt.title("Demand vs Supply (last episode)")
    _savefig("demand_vs_supply")


# ──────────────────────────────────────────────────────────────────────────────
# New Phase 2 plots
# ──────────────────────────────────────────────────────────────────────────────

def plot_inventory_levels(inventory_history: list, disruption_log: list = None):
    """
    Inventory level over time with vertical dashed markers at every
    disruption event, coloured by disruption type.
    """
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(inventory_history, color="#534AB7", linewidth=1.0, label="Inventory")
    ax.axhline(20, color="#BA7517", linewidth=0.8, linestyle="--", alpha=0.6, label="Safety stock (20)")

    if disruption_log:
        added_labels = set()
        for event in disruption_log:
            color = DISRUPTION_COLORS.get(event["type"], "#888780")
            label = event["description"] if event["type"] not in added_labels else None
            ax.axvline(
                event["step"],
                color=color, linewidth=1.2, linestyle=":",
                alpha=0.8, label=label,
            )
            added_labels.add(event["type"])

    ax.set_title("Inventory levels over time")
    ax.set_xlabel("Step")
    ax.set_ylabel("Units")
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(alpha=0.2)
    _savefig("inventory_levels")


def plot_disruption_timeline(
    disruption_log:      list,
    fill_rates_per_step: list,
    demands:             list,
    satisfied:           list,
):
    """
    Two-panel chart.
      Top: demand vs satisfied with shaded disruption windows.
      Bottom: per-step fill rate with shaded windows + mean line.
    """
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True)

    n = len(demands)
    steps = range(n)

    # Panel 1 — demand vs satisfied
    ax1.plot(steps, demands,    color="#378ADD", linewidth=0.7, alpha=0.9, label="Demand")
    ax1.plot(steps, satisfied,  color="#1D9E75", linewidth=0.7, alpha=0.9, label="Satisfied")
    ax1.set_ylabel("Units")
    ax1.set_title("Demand vs Supply with Disruption Windows")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=0.15)

    # Panel 2 — fill rate
    ax2.plot(steps, fill_rates_per_step, color="#534AB7", linewidth=0.8, label="Fill rate")
    mean_fr = np.mean(fill_rates_per_step)
    ax2.axhline(mean_fr, color="#888780", linewidth=0.8, linestyle="--",
                alpha=0.7, label=f"Mean {mean_fr:.3f}")
    ax2.axhline(0.90, color="#1D9E75", linewidth=0.8, linestyle="--",
                alpha=0.7, label="Target 0.90")
    ax2.set_ylabel("Fill rate")
    ax2.set_xlabel("Step")
    ax2.legend(fontsize=8)
    ax2.grid(alpha=0.15)
    ax2.set_ylim(0, 1.05)

    # Shade disruption windows on both panels
    for event in disruption_log:
        color = DISRUPTION_COLORS.get(event["type"], "#888780")
        for ax in (ax1, ax2):
            ax.axvspan(
                event["step"],
                min(event["step"] + event["duration"], n),
                color=color, alpha=0.12,
            )

    # Legend for disruption types
    patches = [
        mpatches.Patch(color=c, alpha=0.4, label=t.replace("_", " ").title())
        for t, c in DISRUPTION_COLORS.items()
    ]
    ax1.legend(handles=ax1.get_legend_handles_labels()[0] + patches, fontsize=7, loc="upper right")

    plt.tight_layout()
    _savefig("disruption_timeline")


def plot_cost_breakdown(
    production_costs: list,
    holding_costs:    list,
    delay_costs:      list,
    sample: int = 500,
):
    """
    Stacked area chart showing the three cost components over the last episode.
    Helps identify whether the agent is over-producing, over-holding, or
    under-serving demand.
    """
    n = min(sample, len(production_costs))
    steps = range(n)
    p = production_costs[-n:]
    h = holding_costs[-n:]
    d = delay_costs[-n:]

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.stackplot(
        steps, p, h, d,
        labels=["Production", "Holding", "Delay penalty"],
        colors=["#378ADD", "#1D9E75", "#E24B4A"],
        alpha=0.75,
    )
    ax.set_title("Cost breakdown per step (last episode)")
    ax.set_xlabel("Step")
    ax.set_ylabel("Cost")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(alpha=0.2)
    _savefig("cost_breakdown")


def plot_episode_metrics(
    episode_fill_rates: list,
    episode_avg_delays: list,
):
    """
    Dual-axis line chart: fill rate (left axis, teal) and avg delay
    (right axis, coral) across all training episodes.
    """
    episodes = range(1, len(episode_fill_rates) + 1)

    fig, ax1 = plt.subplots(figsize=(8, 4))
    color1, color2 = "#1D9E75", "#D85A30"

    ax1.plot(episodes, episode_fill_rates, color=color1, linewidth=1.5, label="Fill rate")
    ax1.set_xlabel("Episode")
    ax1.set_ylabel("Fill rate", color=color1)
    ax1.tick_params(axis="y", labelcolor=color1)
    ax1.set_ylim(0, 1.05)
    ax1.grid(alpha=0.2)

    ax2 = ax1.twinx()
    ax2.plot(episodes, episode_avg_delays, color=color2, linewidth=1.5,
             linestyle="--", label="Avg delay")
    ax2.set_ylabel("Avg delay (units)", color=color2)
    ax2.tick_params(axis="y", labelcolor=color2)

    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=9)

    plt.title("Fill rate and avg delay per episode")
    plt.tight_layout()
    _savefig("episode_metrics")


def plot_resilience_radar(
    normal_metrics:    dict,
    disrupted_metrics: dict,
):
    """
    Radar / spider chart comparing 5 performance axes under normal vs
    disrupted conditions. Visually communicates how much the policy degrades
    when disruptions hit.

    Each metric is normalised to [0, 1] before plotting.
    """
    labels = ["Fill rate", "Low delay", "Cost eff.", "Resilience", "Throughput norm."]

    def normalise(metrics, max_delay=20, max_cost=5000, max_tput=1.0):
        return [
            metrics.get("fill_rate",        0),
            1 - min(metrics.get("avg_delay", 0) / max_delay, 1),
            1 - min(metrics.get("cost_per_step", 0) / max_cost, 1),
            metrics.get("resilience_score", 0),
            min(metrics.get("throughput_norm", 0), 1),
        ]

    vals_normal    = normalise(normal_metrics)
    vals_disrupted = normalise(disrupted_metrics)

    # Close the polygon
    N = len(labels)
    angles = [n / N * 2 * np.pi for n in range(N)]
    angles += angles[:1]
    vals_normal    += vals_normal[:1]
    vals_disrupted += vals_disrupted[:1]

    fig, ax = plt.subplots(figsize=(6, 6), subplot_kw={"polar": True})

    ax.plot(angles, vals_normal,    color="#1D9E75", linewidth=2,   label="Normal")
    ax.fill(angles, vals_normal,    color="#1D9E75", alpha=0.2)
    ax.plot(angles, vals_disrupted, color="#E24B4A", linewidth=2,   label="Disrupted")
    ax.fill(angles, vals_disrupted, color="#E24B4A", alpha=0.15)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylim(0, 1)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0.25", "0.50", "0.75", "1.0"], fontsize=7, alpha=0.6)
    ax.grid(alpha=0.3)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=9)
    ax.set_title("Resilience radar — normal vs disrupted", pad=20)

    plt.tight_layout()
    _savefig("resilience_radar")  