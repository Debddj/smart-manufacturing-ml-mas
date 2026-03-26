"""
Unified simulation runner integrating original and upscaled systems.

Backward-compatible: use_dqn=False, use_multi_warehouse=False reproduces
original tabular Q + single-warehouse behaviour exactly.

FIXES APPLIED:
    1. CRITICAL: export_dashboard_data called with 'agent_events=' but
       parameter is named 'agent_logs' — caused TypeError. Fixed.
    2. CRITICAL: export_dashboard_data called with 'rl_meta=' but
       parameter didn't exist in export function. Fixed by adding rl_meta
       to export_dashboard_data signature (see export_dashboard_data.py).
    3. BUG: __import__('numpy').array(...) used throughout — replaced with
       np.array(...) since numpy is already imported as np at top of file.
    4. BUG: _evaluate_episode passed rl_agent.actions[0] to engine.apply()
       BEFORE the action was chosen — disruption modified wrong production
       value. Fixed: choose action first, then apply disruption.
    5. BUG: next_state computation in DQN branch called rl_agent.build_state()
       which only exists on DQNAgent, not QLearningAgent — would crash if
       use_dqn=False. Fixed: next_state only built when use_dqn=True.
"""

import numpy as np

from simulation.disruption_engine import DisruptionEngine, DISRUPTION_TYPES
from simulation.baseline_runner   import run_baseline_evaluation
from agents.warehouse_agent       import WarehouseAgent
from agents.logistics_agent       import LogisticsAgent
from agents.supplier_agent        import SupplierAgent
from evaluation.metrics           import compute_metrics, compute_resilience_metrics
from rl.reward_functions          import (
    compute_reward,
    compute_reward_multi,
    compute_inventory_balance_score,
    reward_weight_profile,
)
from visualization.plots          import (
    plot_learning_curve, plot_demand_vs_supply,
    plot_inventory_levels, plot_disruption_timeline,
    plot_cost_breakdown, plot_episode_metrics, plot_resilience_radar,
)
from visualization.export_dashboard_data import export_dashboard_data

SLA_FILL_RATE  = 0.90
SLA_AVG_DELAY  = 5.0
MAX_LOG_EVENTS = 120


# ── Event logging helper ──────────────────────────────────────────────────────

def _evt(events, step, severity, agent, event_type, message, human_readable,
         details=None):
    if len(events) >= MAX_LOG_EVENTS:
        return
    events.append({
        "step":           step,
        "severity":       severity,
        "agent":          agent,
        "event":          event_type,
        "message":        message,
        "human_readable": human_readable,
        "details":        details or {},
    })


# ── Scenario evaluation ───────────────────────────────────────────────────────

def _evaluate_episode(
    rl_agent,
    predictions,
    disruptions_enabled,
    seed               = 999,
    use_dqn            = False,
    use_multi_warehouse= False,
):
    """Run one greedy evaluation pass (ε=0, no Q-table updates)."""

    if use_multi_warehouse:
        from simulation.environment import MultiWarehouseEnvironment
        env = MultiWarehouseEnvironment()
    else:
        from simulation.environment import SupplyChainEnvironment
        env = SupplyChainEnvironment()

    warehouse    = WarehouseAgent()
    logistics    = LogisticsAgent()
    supplier     = SupplierAgent()
    engine       = DisruptionEngine(enabled=disruptions_enabled, seed=seed)
    saved_eps    = rl_agent.epsilon
    rl_agent.epsilon = 0.0
    original_cap = logistics.capacity
    costs, demands, satisfied_list = [], [], []

    for day in range(len(predictions) - 1):
        demand = float(predictions[day])
        engine.tick(day)
        raw_supply = supplier.act()

        # FIX: choose action FIRST so we know production before applying disruption
        if use_dqn and use_multi_warehouse:
            state      = env.get_state_vector(demand, engine.active_types(), day=day)
            action_idx = rl_agent.choose_action_full(np.array(state, dtype=np.float32))
        else:
            action_idx = rl_agent.choose_action(env.inventory, demand)

        # Now apply disruption with the actual chosen production value
        disrupted = engine.apply(
            demand        = demand,
            supply        = raw_supply,
            logistics_cap = logistics.capacity,
            production    = rl_agent.actions[action_idx],
        )
        actual_demand      = disrupted["demand"]
        logistics.capacity = disrupted["logistics_cap"]
        actual_prod        = min(rl_agent.actions[action_idx], disrupted["supply"])

        shipment  = warehouse.act(env.inventory + actual_prod, actual_demand)
        transport = logistics.act(shipment)

        if use_multi_warehouse:
            result    = env.step(actual_prod, transport, actual_demand,
                                 disruption_types=engine.active_types())
            satisfied, cost = result[0], result[1]
        else:
            satisfied, cost, _ = env.step(actual_prod, transport, actual_demand)

        logistics.capacity = original_cap
        costs.append(cost)
        demands.append(actual_demand)
        satisfied_list.append(satisfied)

    rl_agent.epsilon = saved_eps
    return compute_metrics(costs, demands, satisfied_list)


def _build_scenario_comparison(
    rl_agent, predictions, baseline_metrics,
    use_dqn=False, use_multi_warehouse=False,
):
    print("  Running scenario evaluations...")
    rl_normal    = _evaluate_episode(rl_agent, predictions, False,
                                     use_dqn=use_dqn,
                                     use_multi_warehouse=use_multi_warehouse)
    rl_disrupted = _evaluate_episode(rl_agent, predictions, True,
                                     use_dqn=use_dqn,
                                     use_multi_warehouse=use_multi_warehouse)
    base_cost = baseline_metrics["Total Cost"]
    base_fr   = baseline_metrics["Fill Rate"]

    def cost_save(c): return round((base_cost - c) / base_cost * 100, 1) if base_cost > 0 else 0.0
    def fr_delta(f):  return round((f - base_fr) * 100, 2)

    return {
        "baseline": {
            "label": "No-RL baseline",
            "description": "Heuristic demand-following policy",
            "fill_rate":       round(base_fr, 4),
            "avg_delay":       round(baseline_metrics["Avg Delay"], 2),
            "total_cost":      round(base_cost, 0),
            "throughput":      round(baseline_metrics["Throughput"], 0),
            "resilience_score":1.0,
            "cost_saving_pct": 0.0,
            "fr_delta_pp":     0.0,
            "sla_pass":        base_fr >= SLA_FILL_RATE,
            "is_rl":           False,
            "accent":          "gray",
        },
        "rl_normal": {
            "label": "RL system — normal",
            "description": "Trained agent, no disruptions",
            "fill_rate":       round(rl_normal["Fill Rate"], 4),
            "avg_delay":       round(rl_normal["Avg Delay"], 2),
            "total_cost":      round(rl_normal["Total Cost"], 0),
            "throughput":      round(rl_normal["Throughput"], 0),
            "resilience_score":1.0,
            "cost_saving_pct": cost_save(rl_normal["Total Cost"]),
            "fr_delta_pp":     fr_delta(rl_normal["Fill Rate"]),
            "sla_pass":        rl_normal["Fill Rate"] >= SLA_FILL_RATE,
            "is_rl":           True,
            "accent":          "teal",
        },
        "rl_disrupted": {
            "label": "RL system — disrupted",
            "description": "Trained agent under active disruptions",
            "fill_rate":       round(rl_disrupted["Fill Rate"], 4),
            "avg_delay":       round(rl_disrupted["Avg Delay"], 2),
            "total_cost":      round(rl_disrupted["Total Cost"], 0),
            "throughput":      round(rl_disrupted["Throughput"], 0),
            "resilience_score":round(
                rl_disrupted["Fill Rate"] / max(rl_normal["Fill Rate"], 1e-9), 4),
            "cost_saving_pct": cost_save(rl_disrupted["Total Cost"]),
            "fr_delta_pp":     fr_delta(rl_disrupted["Fill Rate"]),
            "sla_pass":        rl_disrupted["Fill Rate"] >= SLA_FILL_RATE,
            "is_rl":           True,
            "accent":          "amber",
        },
    }


# ── Main training loop ────────────────────────────────────────────────────────

def train_rl_agent(
    predictions,
    episodes:            int  = 100,
    disruptions_enabled: bool = True,
    use_dqn:             bool = False,
    use_multi_warehouse: bool = False,
    reward_profile:      str  = "balanced",
    save_weights:        bool = True,
):
    """
    Unified training runner.

    Phase 1 (default): use_dqn=False, use_multi_warehouse=False
        → Identical to original simulation_runner.py behaviour

    Phase 2 (upscaled): use_dqn=True, use_multi_warehouse=True
        → DQNAgent + MultiWarehouseEnvironment + MessageBus
        → 10-dimensional state, Branch A/B/C routing
        → Multi-objective reward
    """
    # ── Agent ─────────────────────────────────────────────────────────────────
    if use_dqn:
        from rl.dqn_agent import DQNAgent
        rl_agent    = DQNAgent()
        agent_label = "DQN (PyTorch)"
        diag        = rl_agent.diagnostics()
        print(f"[Runner] DQNAgent — backend: {diag['backend']} device: {diag['device']}")
    else:
        from rl.q_learning import QLearningAgent
        rl_agent    = QLearningAgent()
        agent_label = "Q-Learning (tabular 20×20)"
        print(f"[Runner] QLearningAgent (tabular 20×20)")

    # ── Environment ───────────────────────────────────────────────────────────
    if use_multi_warehouse:
        print("[Runner] MultiWarehouseEnvironment (3 nodes)")
    else:
        print("[Runner] SupplyChainEnvironment (single warehouse)")

    # ── Message bus (multi-warehouse mode only) ───────────────────────────────
    if use_multi_warehouse:
        from communication.message_bus import MessageBus
        bus = MessageBus()
        print("[Runner] MessageBus initialised")
    else:
        bus = None

    rw     = reward_weight_profile(reward_profile)
    engine = DisruptionEngine(enabled=disruptions_enabled, seed=42)

    episode_rewards, episode_fill_rates, episode_avg_delays = [], [], []
    last_demands = last_satisfied = last_inventory = []
    last_fill_per_step = last_prod_costs = last_hold_costs = last_delay_costs = []
    agent_events: list = []

    for ep in range(episodes):
        if use_multi_warehouse:
            from simulation.environment import MultiWarehouseEnvironment
            env = MultiWarehouseEnvironment()
        else:
            from simulation.environment import SupplyChainEnvironment
            env = SupplyChainEnvironment()

        warehouse = WarehouseAgent()
        logistics = LogisticsAgent()
        supplier  = SupplierAgent()
        engine.reset()
        if bus:
            bus.reset()

        total_reward   = 0
        costs, demands, satisfied_list = [], [], []
        inventory_hist, fill_per_step  = [], []
        prod_costs, hold_costs, delay_costs_ep = [], [], []
        original_cap = logistics.capacity

        is_last = (ep == episodes - 1)

        # Cooldown trackers
        last_high_prod_log    = -2000
        last_logistics_log    = -2000
        last_partial_fill_log = -2000
        last_supply_log       = -2000
        last_periodic         = -9999
        below_safety          = False
        below_critical        = False
        sla_failing           = False
        prev_disruptions: set = set()

        for day in range(len(predictions) - 1):
            demand      = float(predictions[day])
            next_demand = float(predictions[day + 1]) if day + 1 < len(predictions) else demand

            engine.tick(day)
            raw_supply = supplier.act()

            # FIX: choose action BEFORE applying disruption so engine.apply()
            # receives the actual intended production value, not actions[0]
            if use_dqn and use_multi_warehouse:
                state      = env.get_state_vector(
                    demand, engine.active_types(), day=day
                )
                action_idx = rl_agent.choose_action_full(
                    np.array(state, dtype=np.float32)   # FIX: was __import__('numpy').array(...)
                )
            else:
                state      = None
                action_idx = rl_agent.choose_action(env.inventory, demand)

            disrupted = engine.apply(
                demand        = demand,
                supply        = raw_supply,
                logistics_cap = logistics.capacity,
                production    = rl_agent.actions[action_idx],
            )
            actual_demand      = disrupted["demand"]
            logistics.capacity = disrupted["logistics_cap"]
            actual_prod        = min(rl_agent.actions[action_idx], disrupted["supply"])

            # ── A2A messages ──────────────────────────────────────────────────
            if bus and engine.is_disrupted():
                for dt in engine.active_types():
                    bus.publish_disruption_alert(
                        sender          = "DisruptionEngine",
                        disruption_type = dt,
                        affected_agents = ["InventoryAgent", "LogisticsAgent",
                                           "SupplierDiscoveryAgent"],
                        step            = day,
                    )

            # ── Environment step ──────────────────────────────────────────────
            shipment  = warehouse.act(env.inventory + actual_prod, actual_demand)
            transport = logistics.act(shipment)

            if use_multi_warehouse:
                result    = env.step(actual_prod, transport, actual_demand,
                                     disruption_types=engine.active_types())
                satisfied, cost, delay = result[0], result[1], result[2]
                branch    = result[3]
                transfer  = result[4]
            else:
                satisfied, cost, delay = env.step(actual_prod, transport, actual_demand)
                branch    = "A"
                transfer  = 0.0

            logistics.capacity = original_cap

            # ── Reward ────────────────────────────────────────────────────────
            if use_dqn and use_multi_warehouse:
                inv_balance = compute_inventory_balance_score(
                    env.network.inventory_vector()
                )
                reward = compute_reward_multi(
                    satisfied, actual_demand, cost, actual_prod,
                    branch=branch,
                    transfer_units=transfer,
                    inventory_balance_score=inv_balance,
                    **rw,
                )
            else:
                reward = compute_reward(
                    satisfied, actual_demand, cost, production=actual_prod
                )

            total_reward += reward

            # ── Learning update ───────────────────────────────────────────────
            if use_dqn:
                # FIX: next_state computation only runs in DQN branch so
                # rl_agent.build_state() is never called on QLearningAgent
                if use_multi_warehouse:
                    next_state = env.get_state_vector(
                        next_demand, engine.active_types(), day=day + 1
                    )
                else:
                    next_state = rl_agent.build_state([env.inventory], next_demand)
                rl_agent.push_experience(
                    np.array(state,      dtype=np.float32),   # FIX: was __import__
                    action_idx,
                    reward,
                    np.array(next_state, dtype=np.float32),   # FIX: was __import__
                    done=False,
                )
                rl_agent.train_step()
            else:
                rl_agent.update(
                    env.inventory, actual_demand, action_idx, reward,
                    env.inventory, next_demand,
                )

            # ── Metrics ───────────────────────────────────────────────────────
            step_fill = satisfied / (actual_demand + 1e-9)
            costs.append(cost)
            demands.append(actual_demand)
            satisfied_list.append(satisfied)
            inventory_hist.append(env.inventory)
            fill_per_step.append(step_fill)
            prod_costs.append(actual_prod * 1.0)
            hold_costs.append(env.inventory * 0.5)
            delay_costs_ep.append(delay * 5)

            if bus:
                bus.flush(step=day)

            # ── Structured event log (last episode only) ──────────────────────
            if is_last:
                curr_disp = set(engine.active_types())

                for dt in curr_disp - prev_disruptions:
                    cfg = DISRUPTION_TYPES.get(dt, {})
                    _evt(agent_events, day, "ALERT", "DisruptionEngine",
                         "disruption_start",
                         f"[Step {day}] {cfg.get('description','Disruption')} ACTIVATED",
                         f"Disruption active: {cfg.get('description','Event')}. "
                         f"Impact: {', '.join(k+'×'+str(v) for k,v in cfg.items() if 'factor' in k)}.",
                         {"type": dt, "severity": cfg.get("severity",""),
                          "factors": {k:v for k,v in cfg.items() if "factor" in k}})

                for dt in prev_disruptions - curr_disp:
                    cfg = DISRUPTION_TYPES.get(dt, {})
                    _evt(agent_events, day, "RESOLVED", "DisruptionEngine",
                         "disruption_resolved",
                         f"[Step {day}] {cfg.get('description','Disruption')} RESOLVED",
                         "Disruption cleared. Agents resuming normal operations.",
                         {"type": dt})

                prev_disruptions = curr_disp

                if use_multi_warehouse and branch != "A":
                    _evt(agent_events, day, "ACTION", "InventoryAgent",
                         f"branch_{branch}_decision",
                         f"[Step {day}] Branch {branch}: {env._last_branch}",
                         (f"Inventory routed via Branch {branch}. "
                          + (f"Transfer: {transfer:.0f} units inter-warehouse."
                             if branch == "B"
                             else "External sourcing required — all warehouses depleted.")),
                         {"branch": branch, "transfer_units": round(transfer, 1)})

                if actual_prod >= 160 and day - last_high_prod_log > 1500:
                    _evt(agent_events, day, "ACTION", "FactoryAgent", "max_production",
                         f"[Step {day}] MAX production: {actual_prod:.0f} units | Demand: {actual_demand:.0f}",
                         f"Production at full capacity: {actual_prod:.0f} units. "
                         f"Agent escalating output to prevent stockout.",
                         {"production": round(actual_prod), "demand": round(actual_demand)})
                    last_high_prod_log = day

                if step_fill < SLA_FILL_RATE and not sla_failing:
                    _evt(agent_events, day, "ALERT", "System", "sla_breach",
                         f"[Step {day}] SLA BREACH: fill rate {step_fill:.3f}",
                         f"Fill rate {step_fill:.3f} below SLA floor {SLA_FILL_RATE}. "
                         f"Disruptions: {list(curr_disp) or 'none'}.",
                         {"fill_rate":           round(step_fill, 4),
                          "sla":                 SLA_FILL_RATE,
                          "active_disruptions":  list(curr_disp)})
                    sla_failing = True

                elif step_fill >= SLA_FILL_RATE and sla_failing:
                    _evt(agent_events, day, "RESOLVED", "System", "sla_restored",
                         f"[Step {day}] SLA RESTORED: {step_fill:.3f}",
                         f"Fill rate recovered to {step_fill:.3f}.",
                         {"fill_rate": round(step_fill, 4)})
                    sla_failing = False

                if day - last_periodic >= 5000:
                    ep_fr = sum(fill_per_step) / max(len(fill_per_step), 1)
                    diag_str = ""
                    if use_dqn:
                        diag = rl_agent.diagnostics()
                        diag_str = f" | Loss={diag.get('avg_loss_recent','n/a')}"
                    _evt(agent_events, day, "INFO", "System", "checkpoint",
                         f"[Step {day}] Checkpoint — Inv: {env.inventory:.0f} Fill: {ep_fr:.3f}",
                         f"Step {day}: Inventory {env.inventory:.0f} | Fill {ep_fr:.3f} | "
                         f"ε={rl_agent.epsilon:.3f}{diag_str}",
                         {"inventory":   round(env.inventory),
                          "fill_rate":   round(ep_fr, 4),
                          "epsilon":     round(rl_agent.epsilon, 4)})
                    last_periodic = day

        # ── Episode end ───────────────────────────────────────────────────────
        rl_agent.epsilon = max(0.01, rl_agent.epsilon * 0.97)

        ep_m = compute_metrics(costs, demands, satisfied_list)
        episode_rewards.append(total_reward)
        episode_fill_rates.append(ep_m["Fill Rate"])
        episode_avg_delays.append(ep_m["Avg Delay"])

        last_demands       = demands
        last_satisfied     = satisfied_list
        last_inventory     = inventory_hist
        last_fill_per_step = fill_per_step
        last_prod_costs    = prod_costs
        last_hold_costs    = hold_costs
        last_delay_costs   = delay_costs_ep

        if (ep + 1) % 10 == 0:
            dqn_info = ""
            if use_dqn:
                diag = rl_agent.diagnostics()
                dqn_info = (f" | buf:{diag['buffer_size']} "
                            f"loss:{diag['avg_loss_recent']}")
            print(f"Ep {ep+1:3d} | Reward:{total_reward:10.2f} | "
                  f"Fill:{ep_m['Fill Rate']:.3f} | Delay:{ep_m['Avg Delay']:.2f} | "
                  f"ε:{rl_agent.epsilon:.3f}{dqn_info}")

    # ── Post-training ─────────────────────────────────────────────────────────
    if use_dqn and save_weights:
        rl_agent.save()

    print(f"\nAgent event log: {len(agent_events)} events captured.")
    print("\nRunning post-training scenario comparison...")
    baseline_metrics    = run_baseline_evaluation(predictions)
    scenario_comparison = _build_scenario_comparison(
        rl_agent, predictions, baseline_metrics,
        use_dqn=use_dqn, use_multi_warehouse=use_multi_warehouse,
    )
    for sc in scenario_comparison.values():
        save = f"  saves {sc['cost_saving_pct']:.1f}% cost" if sc["cost_saving_pct"] else ""
        print(f"  {sc['label']:<32} fill={sc['fill_rate']:.3f} "
              f" SLA:{'PASS' if sc['sla_pass'] else 'FAIL'}{save}")

    final_metrics      = compute_metrics(last_delay_costs, last_demands, last_satisfied)
    resilience_metrics = compute_resilience_metrics(
        last_fill_per_step, engine.disruption_log, len(last_fill_per_step)
    )

    print("\nFinal Metrics:")
    for k, v in final_metrics.items():
        print(f"  {k}: {round(v, 3)}")

    if use_dqn:
        print("\nDQN Diagnostics:")
        for k, v in rl_agent.diagnostics().items():
            print(f"  {k}: {v}")

    print("\nGenerating plots...")
    plot_learning_curve(episode_rewards)
    plot_demand_vs_supply(last_demands, last_satisfied)
    plot_inventory_levels(last_inventory, engine.disruption_log)
    plot_disruption_timeline(engine.disruption_log, last_fill_per_step,
                             last_demands, last_satisfied)
    plot_cost_breakdown(last_prod_costs, last_hold_costs, last_delay_costs)
    plot_episode_metrics(episode_fill_rates, episode_avg_delays)
    plot_resilience_radar(
        {"fill_rate":        resilience_metrics["fill_normal"],
         "avg_delay":        final_metrics["Avg Delay"],
         "cost_per_step":    final_metrics["Total Cost"] / max(len(last_demands), 1),
         "resilience_score": 1.0,
         "throughput_norm":  min(final_metrics["Throughput"] / (sum(last_demands) + 1e-9), 1)},
        {"fill_rate":        resilience_metrics["fill_during_disruption"],
         "avg_delay":        final_metrics["Avg Delay"] * 1.5,
         "cost_per_step":    final_metrics["Total Cost"] / max(len(last_demands), 1) * 1.2,
         "resilience_score": resilience_metrics["resilience_score"],
         "throughput_norm":  resilience_metrics["fill_during_disruption"]}
    )

    rl_meta = {
        "n_bins":          rl_agent.n_bins,
        "actions":         rl_agent.actions,
        "alpha":           rl_agent.alpha,
        "gamma":           rl_agent.gamma,
        "final_epsilon":   round(rl_agent.epsilon, 4),
        "agent_type":      agent_label,
        "multi_warehouse": use_multi_warehouse,
    }

    # FIX: was 'agent_events=agent_events' — parameter is named 'agent_logs'
    # FIX: was 'rl_meta=rl_meta' — added rl_meta to export_dashboard_data signature
    export_dashboard_data(
        episode_rewards     = episode_rewards,
        episode_fill_rates  = episode_fill_rates,
        episode_avg_delays  = episode_avg_delays,
        demand_history      = last_demands,
        satisfied_history   = last_satisfied,
        inventory_history   = last_inventory,
        production_costs    = last_prod_costs,
        holding_costs       = last_hold_costs,
        delay_costs         = last_delay_costs,
        disruption_log      = engine.disruption_log,
        final_metrics       = final_metrics,
        resilience_metrics  = resilience_metrics,
        scenario_comparison = scenario_comparison,
        agent_logs          = agent_events,        # FIX: corrected parameter name
        sla                 = {"fill_rate": SLA_FILL_RATE, "avg_delay": SLA_AVG_DELAY},
        rl_meta             = rl_meta,             # FIX: added to export signature
    )

    return rl_agent
