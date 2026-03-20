from simulation.environment      import SupplyChainEnvironment
from simulation.disruption_engine import DisruptionEngine
from agents.warehouse_agent      import WarehouseAgent
from agents.logistics_agent      import LogisticsAgent
from agents.supplier_agent       import SupplierAgent
from evaluation.metrics          import compute_metrics, compute_resilience_metrics
from rl.q_learning               import QLearningAgent
from rl.reward_functions         import compute_reward
from visualization.plots         import (
    plot_learning_curve,
    plot_demand_vs_supply,
    plot_inventory_levels,
    plot_disruption_timeline,
    plot_cost_breakdown,
    plot_episode_metrics,
    plot_resilience_radar,
)
from visualization.export_dashboard_data import export_dashboard_data


def train_rl_agent(predictions, episodes=100, disruptions_enabled=True):

    rl_agent = QLearningAgent()
    engine   = DisruptionEngine(enabled=disruptions_enabled, seed=42)

    # Per-episode tracking
    episode_rewards    = []
    episode_fill_rates = []
    episode_avg_delays = []

    # Last-episode detail (overwritten each episode, used for plots + export)
    last_demands        = []
    last_satisfied      = []
    last_inventory      = []
    last_fill_per_step  = []
    last_prod_costs     = []
    last_hold_costs     = []
    last_delay_costs    = []

    for ep in range(episodes):

        env       = SupplyChainEnvironment()
        warehouse = WarehouseAgent()
        logistics = LogisticsAgent()
        supplier  = SupplierAgent()
        engine.reset()          # resets active disruptions, keeps full log

        total_reward   = 0
        costs          = []
        demands        = []
        satisfied_list = []
        inventory_hist = []
        fill_per_step  = []
        prod_costs     = []
        hold_costs     = []
        delay_costs_ep = []

        original_logistics_cap = logistics.capacity

        for day in range(len(predictions) - 1):

            demand      = predictions[day]
            next_demand = predictions[day + 1]

            # ── Disruption engine tick ────────────────────────────────────────
            engine.tick(day)
            raw_supply = supplier.act()
            disrupted  = engine.apply(
                demand       = demand,
                supply       = raw_supply,
                logistics_cap= logistics.capacity,
                production   = rl_agent.actions[
                    rl_agent.choose_action(env.inventory, demand)
                ],
            )

            actual_demand      = disrupted["demand"]
            actual_supply      = disrupted["supply"]
            logistics.capacity = disrupted["logistics_cap"]

            # ── RL decision (using observed, disrupted demand + real inventory)
            current_inv = env.inventory
            action_idx  = rl_agent.choose_action(current_inv, actual_demand)
            production  = rl_agent.actions[action_idx]
            actual_prod = min(production * disrupted["production"] / max(production, 1e-5),
                              actual_supply)

            # ── Environment step ─────────────────────────────────────────────
            shipment  = warehouse.act(env.inventory + actual_prod, actual_demand)
            transport = logistics.act(shipment)
            satisfied, cost, delay = env.step(actual_prod, transport, actual_demand)

            # Decompose cost for visualisation
            p_cost = actual_prod * 1.0
            h_cost = env.inventory * 0.5
            d_cost = delay * 5
            prod_costs.append(p_cost)
            hold_costs.append(h_cost)
            delay_costs_ep.append(d_cost)

            # ── Reward + Q-update ─────────────────────────────────────────────
            reward = compute_reward(satisfied, actual_demand, cost, production=actual_prod)
            total_reward += reward

            rl_agent.update(current_inv, actual_demand, action_idx, reward,
                            env.inventory, next_demand)

            # ── Tracking ─────────────────────────────────────────────────────
            step_fill = satisfied / (actual_demand + 1e-9)
            costs.append(cost)
            demands.append(actual_demand)
            satisfied_list.append(satisfied)
            inventory_hist.append(env.inventory)
            fill_per_step.append(step_fill)

            # Reset logistics capacity for next step
            logistics.capacity = original_logistics_cap

        # ── Episode-level epsilon decay ───────────────────────────────────────
        rl_agent.epsilon = max(0.01, rl_agent.epsilon * 0.97)

        ep_metrics = compute_metrics(costs, demands, satisfied_list)
        episode_rewards.append(total_reward)
        episode_fill_rates.append(ep_metrics["Fill Rate"])
        episode_avg_delays.append(ep_metrics["Avg Delay"])

        # Save last-episode detail for plots + export
        last_demands       = demands
        last_satisfied     = satisfied_list
        last_inventory     = inventory_hist
        last_fill_per_step = fill_per_step
        last_prod_costs    = prod_costs
        last_hold_costs    = hold_costs
        last_delay_costs   = delay_costs_ep

        if (ep + 1) % 10 == 0:
            disc_str = f" | Disruptions: {len(engine.disruption_log)}" if disruptions_enabled else ""
            print(
                f"Ep {ep+1:3d} | "
                f"Reward: {total_reward:10.2f} | "
                f"Fill: {ep_metrics['Fill Rate']:.3f} | "
                f"Delay: {ep_metrics['Avg Delay']:.2f} | "
                f"ε: {rl_agent.epsilon:.3f}"
                f"{disc_str}"
            )

    # ── Final metrics ─────────────────────────────────────────────────────────
    final_metrics      = compute_metrics(last_delay_costs, last_demands, last_satisfied)
    resilience_metrics = compute_resilience_metrics(
        last_fill_per_step, engine.disruption_log, len(last_fill_per_step)
    )

    print("\nFinal Metrics:")
    for k, v in final_metrics.items():
        print(f"  {k}: {round(v, 3)}")
    print("\nResilience Metrics:")
    for k, v in resilience_metrics.items():
        print(f"  {k}: {v}")

    # ── Plots ─────────────────────────────────────────────────────────────────
    print("\nGenerating plots...")
    plot_learning_curve(episode_rewards)
    plot_demand_vs_supply(last_demands, last_satisfied)
    plot_inventory_levels(last_inventory, engine.disruption_log)
    plot_disruption_timeline(engine.disruption_log, last_fill_per_step,
                             last_demands, last_satisfied)
    plot_cost_breakdown(last_prod_costs, last_hold_costs, last_delay_costs)
    plot_episode_metrics(episode_fill_rates, episode_avg_delays)

    # Build normalised metric dicts for radar
    normal_metrics    = {
        "fill_rate":        resilience_metrics["fill_normal"],
        "avg_delay":        final_metrics["Avg Delay"],
        "cost_per_step":    final_metrics["Total Cost"] / max(len(last_demands), 1),
        "resilience_score": 1.0,
        "throughput_norm":  min(final_metrics["Throughput"] / (sum(last_demands) + 1e-9), 1),
    }
    disrupted_metrics = {
        "fill_rate":        resilience_metrics["fill_during_disruption"],
        "avg_delay":        final_metrics["Avg Delay"] * 1.5,
        "cost_per_step":    final_metrics["Total Cost"] / max(len(last_demands), 1) * 1.2,
        "resilience_score": resilience_metrics["resilience_score"],
        "throughput_norm":  resilience_metrics["fill_during_disruption"],
    }
    plot_resilience_radar(normal_metrics, disrupted_metrics)

    # ── Export dashboard data ─────────────────────────────────────────────────
    export_dashboard_data(
        episode_rewards    = episode_rewards,
        episode_fill_rates = episode_fill_rates,
        episode_avg_delays = episode_avg_delays,
        demand_history     = last_demands,
        satisfied_history  = last_satisfied,
        inventory_history  = last_inventory,
        production_costs   = last_prod_costs,
        holding_costs      = last_hold_costs,
        delay_costs        = last_delay_costs,
        disruption_log     = engine.disruption_log,
        final_metrics      = final_metrics,
        resilience_metrics = resilience_metrics,
    )

    return rl_agent 