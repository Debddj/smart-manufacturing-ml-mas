from simulation.environment       import SupplyChainEnvironment
from simulation.disruption_engine import DisruptionEngine
from simulation.baseline_runner   import run_baseline_evaluation
from agents.warehouse_agent       import WarehouseAgent
from agents.logistics_agent       import LogisticsAgent
from agents.supplier_agent        import SupplierAgent
from evaluation.metrics           import compute_metrics, compute_resilience_metrics
from rl.q_learning                import QLearningAgent
from rl.reward_functions          import compute_reward
from visualization.plots          import (
    plot_learning_curve, plot_demand_vs_supply,
    plot_inventory_levels, plot_disruption_timeline,
    plot_cost_breakdown, plot_episode_metrics, plot_resilience_radar,
)
from visualization.export_dashboard_data import export_dashboard_data

SLA_FILL_RATE = 0.90
SLA_AVG_DELAY = 5.0

def _evaluate_episode(rl_agent, predictions, disruptions_enabled, seed=999):
    env       = SupplyChainEnvironment()
    warehouse = WarehouseAgent()
    logistics = LogisticsAgent()
    supplier  = SupplierAgent()
    engine    = DisruptionEngine(enabled=disruptions_enabled, seed=seed)

    saved_eps        = rl_agent.epsilon
    rl_agent.epsilon = 0.0
    original_cap     = logistics.capacity

    costs, demands, satisfied_list = [], [], []

    for day in range(len(predictions) - 1):
        demand = float(predictions[day])
        engine.tick(day)
        raw_supply = supplier.act()
        action_idx = rl_agent.choose_action(env.inventory, demand)
        disrupted  = engine.apply(
            demand=demand, supply=raw_supply,
            logistics_cap=logistics.capacity,
            production=rl_agent.actions[action_idx],
        )
        actual_demand      = disrupted["demand"]
        logistics.capacity = disrupted["logistics_cap"]
        actual_prod        = min(rl_agent.actions[action_idx], disrupted["supply"])
        shipment           = warehouse.act(env.inventory + actual_prod, actual_demand)
        transport          = logistics.act(shipment)
        satisfied, cost, _ = env.step(actual_prod, transport, actual_demand)
        logistics.capacity = original_cap
        costs.append(cost)
        demands.append(actual_demand)
        satisfied_list.append(satisfied)

    rl_agent.epsilon = saved_eps
    return compute_metrics(costs, demands, satisfied_list)


def _build_scenario_comparison(rl_agent, predictions, baseline_metrics):
    """
    Build the three-scenario comparison dict.

    The headline value metric is COST EFFICIENCY — not fill rate improvement.
    Both the baseline and RL system achieve high fill rates, but the RL system
    does so at substantially lower cost by avoiding over-production and excess
    inventory. This is the actual industry value proposition.

    Improvement badges show:
      - Cost reduction vs baseline (lower cost = better)
      - Fill rate parity (to show the RL doesn't sacrifice service level)
    """
    print("  Running scenario evaluations...")
    rl_normal    = _evaluate_episode(rl_agent, predictions, disruptions_enabled=False)
    rl_disrupted = _evaluate_episode(rl_agent, predictions, disruptions_enabled=True)

    base_cost = baseline_metrics["Total Cost"]
    base_fr   = baseline_metrics["Fill Rate"]

    def cost_saving_pct(cost):
        if base_cost <= 0:
            return 0.0
        return round((base_cost - cost) / base_cost * 100, 1)

    def fr_delta(fr):
        return round((fr - base_fr) * 100, 2)

    return {
        "baseline": {
            "label":            "No-RL baseline",
            "description":      "Heuristic demand-following policy",
            "fill_rate":        round(base_fr, 4),
            "avg_delay":        round(baseline_metrics["Avg Delay"], 2),
            "total_cost":       round(base_cost, 0),
            "throughput":       round(baseline_metrics["Throughput"], 0),
            "resilience_score": 1.0,
            "cost_saving_pct":  0.0,
            "fr_delta_pp":      0.0,
            "sla_pass":         base_fr >= SLA_FILL_RATE,
            "is_rl":            False,
            "accent":           "gray",
        },
        "rl_normal": {
            "label":            "RL system — normal",
            "description":      "Trained Q-agent, no disruptions",
            "fill_rate":        round(rl_normal["Fill Rate"], 4),
            "avg_delay":        round(rl_normal["Avg Delay"], 2),
            "total_cost":       round(rl_normal["Total Cost"], 0),
            "throughput":       round(rl_normal["Throughput"], 0),
            "resilience_score": 1.0,
            "cost_saving_pct":  cost_saving_pct(rl_normal["Total Cost"]),
            "fr_delta_pp":      fr_delta(rl_normal["Fill Rate"]),
            "sla_pass":         rl_normal["Fill Rate"] >= SLA_FILL_RATE,
            "is_rl":            True,
            "accent":           "teal",
        },
        "rl_disrupted": {
            "label":            "RL system — disrupted",
            "description":      "Trained Q-agent under active disruptions",
            "fill_rate":        round(rl_disrupted["Fill Rate"], 4),
            "avg_delay":        round(rl_disrupted["Avg Delay"], 2),
            "total_cost":       round(rl_disrupted["Total Cost"], 0),
            "throughput":       round(rl_disrupted["Throughput"], 0),
            "resilience_score": round(
                rl_disrupted["Fill Rate"] / max(rl_normal["Fill Rate"], 1e-9), 4
            ),
            "cost_saving_pct":  cost_saving_pct(rl_disrupted["Total Cost"]),
            "fr_delta_pp":      fr_delta(rl_disrupted["Fill Rate"]),
            "sla_pass":         rl_disrupted["Fill Rate"] >= SLA_FILL_RATE,
            "is_rl":            True,
            "accent":           "amber",
        },
    }


def train_rl_agent(predictions, episodes=100, disruptions_enabled=True):
    from simulation.logger import MASLogger
    logger = MASLogger()

    rl_agent = QLearningAgent()
    engine = DisruptionEngine(enabled=disruptions_enabled, seed=42)

    episode_rewards, episode_fill_rates, episode_avg_delays = [], [], []
    last_demands = last_satisfied = last_inventory = []
    last_fill_per_step = last_prod_costs = last_hold_costs = last_delay_costs = []

    for ep in range(episodes):
        env = SupplyChainEnvironment()
        warehouse = WarehouseAgent()
        logistics = LogisticsAgent()
        supplier = SupplierAgent()
        engine.reset()

        previous_inventory = env.inventory

        total_reward = 0
        costs = []
        demands = []
        satisfied_list = []
        inventory_hist = []
        fill_per_step = []
        prod_costs, hold_costs, delay_costs_ep = [], [], []
        original_cap = logistics.capacity

        for day in range(len(predictions) - 1):
            demand = float(predictions[day])
            next_demand = float(predictions[day + 1])

            engine.tick(day)
            raw_supply = supplier.act()

            # RL decision
            current_inv = env.inventory
            action_idx = rl_agent.choose_action(current_inv, demand)

            disrupted = engine.apply(
                demand=demand,
                supply=raw_supply,
                logistics_cap=logistics.capacity,
                production=rl_agent.actions[action_idx],
            )

            actual_demand = disrupted["demand"]
            logistics.capacity = disrupted["logistics_cap"]

            actual_prod = min(rl_agent.actions[action_idx], disrupted["supply"])

            shipment = warehouse.act(env.inventory + actual_prod, actual_demand)
            transport = logistics.act(shipment)

            satisfied, cost, delay = env.step(actual_prod, transport, actual_demand)

            # ===================== LOGGING =====================
            ENABLE_LOGGING = (ep == episodes - 1)

            if ENABLE_LOGGING:

                # 🔴 CRITICAL: Only real disruptions
                if disrupted["demand"] > demand * 1.3:
                    logger.log(day, "CRITICAL", "DisruptionEngine",
                        f"Demand spike: {demand:.1f} → {actual_demand:.1f}")

                # 🟡 WARNING: Only severe inventory shortage
                if env.inventory <= 5:
                    logger.log(day, "WARNING", "WarehouseAgent",
                        f"Stockout risk: inventory={env.inventory:.1f}")

                # 🔵 ACTION: Only when production changes significantly
                if abs(actual_prod - demand) > 40:
                    logger.log(day, "ACTION", "FactoryAgent",
                        f"Adjusted production: {actual_prod} (Demand: {actual_demand:.1f})")

                # 🔵 INFO: Only severe logistics bottleneck
                if shipment > 0 and transport / shipment < 0.5:
                    logger.log(day, "INFO", "LogisticsAgent",
                        f"Severe bottleneck: {transport}/{shipment}")

                # 🟢 RESOLVED: Only when recovering from crisis
                if env.inventory > 50 and delay == 0 and previous_inventory <= 10:
                    logger.log(day, "RESOLVED", "SupplyChainEnv",
                        f"Recovered: inventory={env.inventory:.1f}")

            # ===================================================

            # Cost breakdown
            prod_costs.append(actual_prod * 1.0)
            hold_costs.append(env.inventory * 0.5)
            delay_costs_ep.append(delay * 5)

            # Reward + learning
            reward = compute_reward(satisfied, actual_demand, cost, production=actual_prod)
            total_reward += reward

            rl_agent.update(
                current_inv,
                actual_demand,
                action_idx,
                reward,
                env.inventory,
                next_demand
            )

            logistics.capacity = original_cap

            costs.append(cost)
            demands.append(actual_demand)
            satisfied_list.append(satisfied)
            inventory_hist.append(env.inventory)
            fill_per_step.append(satisfied / (actual_demand + 1e-9))

        rl_agent.epsilon = max(0.01, rl_agent.epsilon * 0.97)

        ep_m = compute_metrics(costs, demands, satisfied_list)

        episode_rewards.append(total_reward)
        episode_fill_rates.append(ep_m["Fill Rate"])
        episode_avg_delays.append(ep_m["Avg Delay"])

        last_demands = demands
        last_satisfied = satisfied_list
        last_inventory = inventory_hist
        last_fill_per_step = fill_per_step
        last_prod_costs = prod_costs
        last_hold_costs = hold_costs
        last_delay_costs = delay_costs_ep

        if (ep + 1) % 10 == 0:
            disc = f" | events: {len(engine.disruption_log)}" if disruptions_enabled else ""
            print(f"Ep {ep+1:3d} | Reward:{total_reward:10.2f} | "
                  f"Fill:{ep_m['Fill Rate']:.3f} | Delay:{ep_m['Avg Delay']:.2f} | "
                  f"ε:{rl_agent.epsilon:.3f}{disc}")

    previous_inventory = env.inventory
    # ================= POST TRAINING =================

    print("\nRunning post-training scenario comparison...")
    baseline_metrics = run_baseline_evaluation(predictions)
    scenario_comparison = _build_scenario_comparison(
        rl_agent, predictions, baseline_metrics
    )

    for sc in scenario_comparison.values():
        sla = "PASS" if sc["sla_pass"] else "FAIL"
        save = f" saves {sc['cost_saving_pct']:.1f}% cost vs baseline" if sc["cost_saving_pct"] else ""
        print(f" {sc['label']:<30} fill={sc['fill_rate']:.3f} "
              f"cost={sc['total_cost']:,.0f} SLA:{sla}{save}")

    final_metrics = compute_metrics(last_delay_costs, last_demands, last_satisfied)
    resilience_metrics = compute_resilience_metrics(
        last_fill_per_step, engine.disruption_log, len(last_fill_per_step)
    )

    print("\nFinal Metrics:")
    for k, v in final_metrics.items():
        print(f" {k}: {round(v, 3)}")

    print("\nGenerating plots...")
    plot_learning_curve(episode_rewards)
    plot_demand_vs_supply(last_demands, last_satisfied)
    plot_inventory_levels(last_inventory, engine.disruption_log)
    plot_disruption_timeline(
        engine.disruption_log, last_fill_per_step,
        last_demands, last_satisfied
    )
    plot_cost_breakdown(last_prod_costs, last_hold_costs, last_delay_costs)
    plot_episode_metrics(episode_fill_rates, episode_avg_delays)

    export_dashboard_data(
        episode_rewards=episode_rewards,
        episode_fill_rates=episode_fill_rates,
        episode_avg_delays=episode_avg_delays,
        demand_history=last_demands,
        satisfied_history=last_satisfied,
        inventory_history=last_inventory,
        production_costs=last_prod_costs,
        holding_costs=last_hold_costs,
        delay_costs=last_delay_costs,
        disruption_log=engine.disruption_log,
        final_metrics=final_metrics,
        resilience_metrics=resilience_metrics,
        scenario_comparison=scenario_comparison,
        sla={"fill_rate": SLA_FILL_RATE, "avg_delay": SLA_AVG_DELAY},
    )
    # Export logs
    logger.export("outputs/interaction_logs.json")
    print("Logs exported to outputs/interaction_logs.json")
    
    return rl_agent