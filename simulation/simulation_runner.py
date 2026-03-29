"""
Unified simulation runner — integrates all agents from the architecture diagram.

BUGS FIXED IN THIS VERSION:
    BUG 1 (CRASH): FulfillmentAgent, LastMileAgent, ProcurementAgent, DistributionHubAgent,
        SupplierDiscoveryAgent created once outside the episode loop but history lists are
        NEVER reset. By episode 80 this accumulates ~25 GB of Python dicts, crashing
        the desktop. Fix: call .reset() on all diagram agents at the start of each episode.

    BUG 2 (WRONG Q-UPDATE): env.inventory was read AFTER env.step(), so both the current
        state (inv) and next state (next_inv) in rl_agent.update() were identical post-step
        values. Fix: capture pre_step_inv = env.inventory BEFORE calling env.step().

    BUG 3 (WRONG COST METRIC): final_metrics was computed with compute_metrics(last_delay_costs,
        ...) passing only the delay-cost component instead of total operational cost.
        Fix: track last_costs = costs (full per-step cost from env.step()) and use that.

    BUG 4 (WRONG RESILIENCE): engine.disruption_log accumulates across all episodes (~82K
        entries over 100 episodes). compute_resilience_metrics was receiving the full
        cross-episode log, making every step appear disrupted.
        Fix: track episode start index, pass only the last episode's slice.

    BUG 5 (DUPLICATE ARGS): _log_warehouse_events was called with duplicate
        below_safety_flag / below_critical_flag values for the last two arguments.
        Fix: removed the redundant prev_below_safety / prev_below_critical parameters.

    BUG 6 (PLOT SLOW): No downsampling on 182K-point data passed to matplotlib.
        Fix: downsample large arrays to max 2000 points before passing to plot functions.
"""

import numpy as np

from simulation.disruption_engine    import DisruptionEngine, DISRUPTION_TYPES
from simulation.baseline_runner      import run_baseline_evaluation
from agents.warehouse_agent          import WarehouseAgent
from agents.logistics_agent          import LogisticsAgent
from agents.supplier_agent           import SupplierAgent
from agents.procurement_agent        import ProcurementAgent
from agents.fulfillment_agent        import FulfillmentAgent
from agents.last_mile_agent          import LastMileAgent
from agents.distribution_hub_agent   import DistributionHubAgent
from agents.supplier_discovery_agent import SupplierDiscoveryAgent
from communication.message_bus       import MessageBus
from evaluation.metrics              import compute_metrics, compute_resilience_metrics
from rl.reward_functions             import (
    compute_reward, compute_reward_multi,
    compute_inventory_balance_score, reward_weight_profile,
)
from visualization.plots             import (
    plot_learning_curve, plot_demand_vs_supply,
    plot_inventory_levels, plot_disruption_timeline,
    plot_cost_breakdown, plot_episode_metrics, plot_resilience_radar,
)
from visualization.export_dashboard_data import export_dashboard_data

SLA_FILL_RATE  = 0.90
SLA_AVG_DELAY  = 5.0
MAX_LOG_EVENTS = 200

# Safety thresholds for WarehouseAgent alerting
SAFETY_STOCK   = 20.0
CRITICAL_STOCK = 5.0

# BUG 6 FIX: Downsample large arrays to this many points before passing to plots.
PLOT_MAX_POINTS = 2000


# ── Downsampler helper ────────────────────────────────────────────────────────

def _downsample(data, max_pts=PLOT_MAX_POINTS):
    """Return an evenly-spaced subsample of `data` at most `max_pts` long."""
    n = len(data)
    if n <= max_pts:
        return list(data)
    step = max(1, n // max_pts)
    return list(data)[::step][:max_pts]


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


# ── Warehouse event helpers ───────────────────────────────────────────────────

# BUG 5 FIX: Removed unused prev_below_safety / prev_below_critical parameters.
def _log_warehouse_events(
    events, day, inventory, demand, satisfied, actual_prod,
    active_disruptions,
    below_safety_flag, below_critical_flag,
):
    """
    Emit structured WarehouseAgent events based on inventory thresholds.
    Returns updated (below_safety_flag, below_critical_flag).
    """
    shortfall = max(0.0, demand - satisfied)
    fill_pct  = (satisfied / demand * 100) if demand > 0 else 100.0

    # Critical stockout — entered for the first time
    if inventory <= 0 and not below_critical_flag:
        _evt(events, day, "ALERT", "WarehouseAgent", "inventory_critical",
             f"[Step {day}] CRITICAL: Inventory at {inventory:.0f} units — near stockout | Demand: {demand:.0f}",
             f"CRITICAL ALERT — Warehouse nearly depleted: {inventory:.0f} units remaining "
             f"against {demand:.0f} demand. Immediate replenishment required. "
             f"Partial fulfilment enforced — {shortfall:.0f} units unserved. "
             f"SLA breach imminent if production does not escalate within 2 steps.",
             {"inventory": round(inventory), "demand": round(demand),
              "shortfall": round(shortfall), "safety_stock": SAFETY_STOCK})
        below_critical_flag = True

    # Below safety stock (not yet critical) — first entry
    elif 0 < inventory < SAFETY_STOCK and not below_safety_flag:
        _evt(events, day, "WARNING", "WarehouseAgent", "inventory_below_safety",
             f"[Step {day}] Inventory below safety stock: {inventory:.0f}/{SAFETY_STOCK:.0f} units | Demand: {demand:.0f}",
             f"Inventory warning: Stock level at {inventory:.0f} units — below the "
             f"{SAFETY_STOCK:.0f}-unit safety buffer. Warehouse operating in risk zone. "
             f"RL agent should be increasing production orders now. Vulnerable to any "
             f"demand spike or further supplier disruption.",
             {"inventory": round(inventory), "safety_stock": SAFETY_STOCK,
              "demand": round(demand), "buffer_remaining": round(inventory)})
        below_safety_flag = True

    # Partial fulfilment this step (fill rate < 90%)
    if shortfall > 0 and fill_pct < 90:
        _evt(events, day, "WARNING", "WarehouseAgent", "partial_fulfilment",
             f"[Step {day}] Partial fulfilment: {satisfied:.0f}/{demand:.0f} units ({fill_pct:.1f}%)",
             f"Service degraded: {satisfied:.0f} of {demand:.0f} units fulfilled "
             f"({fill_pct:.1f}% fill rate this step). {shortfall:.0f} units unserved "
             f"— contributing to delay penalty. Cause: disruption impact.",
             {"satisfied": round(satisfied), "demand": round(demand),
              "fill_pct": round(fill_pct, 1), "delay_units": round(shortfall)})

    # Recovery — back above safety stock
    if below_safety_flag and inventory >= SAFETY_STOCK:
        _evt(events, day, "RESOLVED", "WarehouseAgent", "inventory_restored",
             f"[Step {day}] Inventory restored to {inventory:.0f} units — safety threshold cleared",
             f"Warehouse recovery confirmed: Inventory back above {SAFETY_STOCK:.0f}-unit "
             f"safety threshold at {inventory:.0f} units. Full demand coverage restored. "
             f"RL agent successfully navigated low-stock period — buffer rebuilt within "
             f"operational parameters.",
             {"inventory": round(inventory), "safety_stock": SAFETY_STOCK})
        below_safety_flag   = False
        below_critical_flag = False

    return below_safety_flag, below_critical_flag


# ── Scenario evaluation ───────────────────────────────────────────────────────

def _evaluate_episode(
    rl_agent, predictions, disruptions_enabled, seed=999,
    use_dqn=False, use_multi_warehouse=False,
):
    """Run one greedy evaluation pass (ε=0, no Q-table updates)."""
    if use_multi_warehouse:
        from simulation.environment import MultiWarehouseEnvironment
        env = MultiWarehouseEnvironment()
    else:
        from simulation.environment import SupplyChainEnvironment
        env = SupplyChainEnvironment()

    warehouse = WarehouseAgent()
    logistics = LogisticsAgent()
    supplier  = SupplierAgent()
    engine    = DisruptionEngine(enabled=disruptions_enabled, seed=seed)

    saved_eps = rl_agent.epsilon
    rl_agent.epsilon = 0.0
    original_cap = logistics.capacity
    costs, demands, satisfied_list = [], [], []

    for day in range(len(predictions) - 1):
        demand = float(predictions[day])
        engine.tick(day)
        raw_supply = supplier.act()

        if use_dqn and use_multi_warehouse:
            state      = env.get_state_vector(demand, engine.active_types(), day=day)
            action_idx = rl_agent.choose_action_full(np.array(state, dtype=np.float32))
        else:
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
            "label": "No-RL baseline", "description": "Heuristic demand-following policy",
            "fill_rate": round(base_fr, 4), "avg_delay": round(baseline_metrics["Avg Delay"], 2),
            "total_cost": round(base_cost, 0), "throughput": round(baseline_metrics["Throughput"], 0),
            "resilience_score": 1.0, "cost_saving_pct": 0.0, "fr_delta_pp": 0.0,
            "sla_pass": base_fr >= SLA_FILL_RATE, "is_rl": False, "accent": "gray",
        },
        "rl_normal": {
            "label": "RL system — normal", "description": "Trained agent, no disruptions",
            "fill_rate": round(rl_normal["Fill Rate"], 4), "avg_delay": round(rl_normal["Avg Delay"], 2),
            "total_cost": round(rl_normal["Total Cost"], 0), "throughput": round(rl_normal["Throughput"], 0),
            "resilience_score": 1.0, "cost_saving_pct": cost_save(rl_normal["Total Cost"]),
            "fr_delta_pp": fr_delta(rl_normal["Fill Rate"]),
            "sla_pass": rl_normal["Fill Rate"] >= SLA_FILL_RATE, "is_rl": True, "accent": "teal",
        },
        "rl_disrupted": {
            "label": "RL system — disrupted", "description": "Trained agent under active disruptions",
            "fill_rate": round(rl_disrupted["Fill Rate"], 4), "avg_delay": round(rl_disrupted["Avg Delay"], 2),
            "total_cost": round(rl_disrupted["Total Cost"], 0), "throughput": round(rl_disrupted["Throughput"], 0),
            "resilience_score": round(
                rl_disrupted["Fill Rate"] / max(rl_normal["Fill Rate"], 1e-9), 4),
            "cost_saving_pct": cost_save(rl_disrupted["Total Cost"]),
            "fr_delta_pp": fr_delta(rl_disrupted["Fill Rate"]),
            "sla_pass": rl_disrupted["Fill Rate"] >= SLA_FILL_RATE, "is_rl": True, "accent": "amber",
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
    # ── Agent selection ────────────────────────────────────────────────────────
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

    if use_multi_warehouse:
        print("[Runner] MultiWarehouseEnvironment (3 nodes)")
    else:
        print("[Runner] SupplyChainEnvironment (single warehouse)")

    if use_multi_warehouse:
        bus = MessageBus()
        print("[Runner] MessageBus initialised")
    else:
        bus = None

    # ── BUG 1 FIX: Create diagram agents once here; reset() at top of each episode loop ──
    # Previously these were created once and NEVER reset, so their history lists
    # grew to 182K × N_episodes entries, consuming ~25 GB of RAM by episode 80.
    procurement_agent  = ProcurementAgent()
    fulfillment_agent  = FulfillmentAgent()
    last_mile_agent    = LastMileAgent()
    dist_hub_agent     = DistributionHubAgent()
    supplier_discovery = SupplierDiscoveryAgent()

    rw     = reward_weight_profile(reward_profile)
    engine = DisruptionEngine(enabled=disruptions_enabled, seed=42)

    episode_rewards, episode_fill_rates, episode_avg_delays = [], [], []

    # BUG 3 FIX: Track last_costs (total per-step cost) — was never tracked before
    last_costs = last_demands = last_satisfied = last_inventory = []
    last_fill_per_step = last_prod_costs = last_hold_costs = last_delay_costs = []
    agent_events: list = []

    # BUG 4 FIX: Track the disruption log index at the start of the final episode
    # so we pass only that episode's events to compute_resilience_metrics.
    last_episode_disruption_start = 0

    for ep in range(episodes):
        # ── BUG 1 FIX: Reset all diagram agents at episode start ──────────────
        # This clears the history lists that caused ~25 GB memory accumulation.
        procurement_agent.reset()
        fulfillment_agent.reset()
        last_mile_agent.reset()
        dist_hub_agent.reset()
        supplier_discovery.reset()

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

        # BUG 4 FIX: Record where this episode's disruptions start in the log
        episode_disruption_start = len(engine.disruption_log)

        total_reward = 0
        # BUG 3 FIX: Track full per-step cost (not just delay component)
        costs, demands, satisfied_list = [], [], []
        inventory_hist, fill_per_step  = [], []
        prod_costs, hold_costs, delay_costs_ep = [], [], []
        original_cap = logistics.capacity

        is_last = (ep == episodes - 1)
        if is_last:
            # Record where the last episode's disruptions start
            last_episode_disruption_start = episode_disruption_start

        # Cooldown / state trackers
        last_high_prod_log    = -2000
        last_logistics_log    = -2000
        last_supply_log       = -2000
        last_periodic         = -9999
        below_safety_flag     = False
        below_critical_flag   = False
        sla_failing           = False
        prev_disruptions: set = set()

        for day in range(len(predictions) - 1):
            demand      = float(predictions[day])
            next_demand = float(predictions[day + 1]) if day + 1 < len(predictions) else demand

            engine.tick(day)
            raw_supply = supplier.act()

            if use_dqn and use_multi_warehouse:
                state      = env.get_state_vector(demand, engine.active_types(), day=day)
                action_idx = rl_agent.choose_action_full(np.array(state, dtype=np.float32))
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
                        sender="DisruptionEngine", disruption_type=dt,
                        affected_agents=["InventoryAgent", "LogisticsAgent",
                                         "SupplierDiscoveryAgent"],
                        step=day,
                    )

            # ── Procurement decision ──────────────────────────────────────────
            procurement_qty = procurement_agent.process_order(
                required=actual_prod,
                inventory=env.inventory,
                demand=actual_demand,
                disruptions=engine.active_types(),
            )

            # ── BUG 2 FIX: Capture pre-step inventory for correct Bellman state ──
            # Before this fix, env.inventory was read AFTER env.step(), so both
            # current-state and next-state in rl_agent.update() were the same
            # post-step value, corrupting the Q-table.
            pre_step_inv = env.inventory

            # ── Environment step ───────────────────────────────────────────────
            shipment  = warehouse.act(env.inventory + procurement_qty, actual_demand)
            transport = logistics.act(shipment)

            if use_multi_warehouse:
                result    = env.step(actual_prod, transport, actual_demand,
                                     disruption_types=engine.active_types())
                satisfied, cost, delay = result[0], result[1], result[2]
                branch    = result[3]
                transfer  = result[4]

                dist_hub_agent.route(
                    branch=branch, transfer_units=transfer,
                    warehouses=["A", "B", "C"], step=day,
                )

                if branch == "C":
                    alt_supplier = supplier_discovery.find_supplier(
                        units_needed=actual_demand - satisfied,
                        disruptions=engine.active_types(),
                    )
                    if is_last and alt_supplier:
                        _evt(agent_events, day, "ACTION", "SupplierDiscoveryAgent",
                             "supplier_found",
                             f"[Step {day}] Alt supplier found: {alt_supplier['name']} — "
                             f"{alt_supplier['capacity']:.0f} units available",
                             f"External sourcing activated. Supplier '{alt_supplier['name']}' "
                             f"selected with {alt_supplier['capacity']:.0f}-unit capacity "
                             f"and {alt_supplier['reliability']*100:.0f}% reliability.",
                             alt_supplier)
            else:
                satisfied, cost, delay = env.step(actual_prod, transport, actual_demand)
                branch   = "A"
                transfer = 0.0

            # ── Fulfillment & last-mile ────────────────────────────────────────
            delivered = fulfillment_agent.fulfill(
                satisfied=satisfied, demand=actual_demand,
                inventory=env.inventory,
            )
            last_mile_result = last_mile_agent.deliver(
                units=delivered, step=day,
                disruptions=engine.active_types(),
            )

            logistics.capacity = original_cap

            # ── Reward ─────────────────────────────────────────────────────────
            if use_dqn and use_multi_warehouse:
                inv_balance = compute_inventory_balance_score(
                    env.network.inventory_vector()
                )
                reward = compute_reward_multi(
                    satisfied, actual_demand, cost, actual_prod,
                    branch=branch, transfer_units=transfer,
                    inventory_balance_score=inv_balance, **rw,
                )
            else:
                reward = compute_reward(
                    satisfied, actual_demand, cost, production=actual_prod
                )

            total_reward += reward

            # ── BUG 2 FIX: Use pre_step_inv as current state, env.inventory as next ──
            if use_dqn:
                if use_multi_warehouse:
                    next_state = env.get_state_vector(
                        next_demand, engine.active_types(), day=day + 1
                    )
                else:
                    next_state = rl_agent.build_state([env.inventory], next_demand)
                rl_agent.push_experience(
                    np.array(state,      dtype=np.float32),
                    action_idx, reward,
                    np.array(next_state, dtype=np.float32),
                    done=False,
                )
                rl_agent.train_step()
            else:
                # BUG 2 FIX: pre_step_inv (before step) → current state
                #             env.inventory (after step)  → next state
                rl_agent.update(
                    pre_step_inv, actual_demand, action_idx, reward,
                    env.inventory, next_demand,
                )

            # ── Metrics accumulation ──────────────────────────────────────────
            step_fill = satisfied / (actual_demand + 1e-9)
            costs.append(cost)               # BUG 3 FIX: full cost from env.step()
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

                # Disruption start / resolved
                for dt in curr_disp - prev_disruptions:
                    cfg = DISRUPTION_TYPES.get(dt, {})
                    _evt(agent_events, day, "ALERT", "DisruptionEngine",
                         "disruption_start",
                         f"[Step {day}] {cfg.get('description','Disruption')} ACTIVATED "
                         f"— expected {cfg.get('duration_range', '')} steps",
                         f"Disruption detected: {cfg.get('description', dt)} now active. "
                         f"All downstream agents operating under degraded conditions. "
                         f"Impact: {', '.join(k+'×'+str(v) for k,v in cfg.items() if 'factor' in k)}. "
                         f"Monitoring recovery.",
                         {"type": dt, "severity": cfg.get("severity", ""),
                          "factors": {k: v for k, v in cfg.items() if "factor" in k}})

                for dt in prev_disruptions - curr_disp:
                    cfg = DISRUPTION_TYPES.get(dt, {})
                    _evt(agent_events, day, "RESOLVED", "DisruptionEngine",
                         "disruption_resolved",
                         f"[Step {day}] {cfg.get('description','Disruption')} RESOLVED "
                         f"— normal operations restored",
                         f"Disruption cleared: {cfg.get('description', dt)} no longer active. "
                         f"Agents resuming standard operating parameters. "
                         f"Expect inventory recovery within 3–8 steps as production ramps to meet backlog.",
                         {"type": dt})

                prev_disruptions = curr_disp

                # SupplierAgent: supply_reduced during disruption
                if "supplier_failure" in curr_disp and day - last_supply_log > 800:
                    _evt(agent_events, day, "INFO", "SupplierAgent", "supply_reduced",
                         f"[Step {day}] Supplier delivering reduced batch: {raw_supply:.0f} units "
                         f"(disruption in effect)",
                         f"Reduced supply batch dispatched: {raw_supply:.0f} units. "
                         f"Supplier disruption compressing output. Factory will supplement "
                         f"from existing warehouse reserves to meet current demand of "
                         f"{actual_demand:.0f} units.",
                         {"available": round(raw_supply), "demand": round(actual_demand)})
                    last_supply_log = day

                # LogisticsAgent: logistics_disrupted
                if "logistics_breakdown" in curr_disp and day - last_logistics_log > 0:
                    _evt(agent_events, day, "ALERT", "LogisticsAgent", "logistics_disrupted",
                         f"[Step {day}] Logistics breakdown: fleet at {logistics.capacity:.0f} "
                         f"unit capacity (normal: {original_cap:.0f})",
                         f"Fleet severely degraded: operating at {logistics.capacity:.0f}/"
                         f"{original_cap:.0f} units "
                         f"({logistics.capacity/original_cap*100:.0f}% capacity). "
                         f"Priority dispatch only — {transport:.0f} units moving. "
                         f"Non-critical delivery timelines suspended until fleet recovery confirmed.",
                         {"current_capacity": round(logistics.capacity),
                          "normal_capacity":  round(original_cap),
                          "units_dispatched": round(transport),
                          "disruption":       "logistics_breakdown"})
                    last_logistics_log = day

                # BUG 5 FIX: Removed duplicate flag parameters from the call
                below_safety_flag, below_critical_flag = _log_warehouse_events(
                    agent_events, day, env.inventory, actual_demand, satisfied,
                    actual_prod, curr_disp,
                    below_safety_flag, below_critical_flag,
                )

                # FactoryAgent: high / max production decisions
                if actual_prod >= 160 and day - last_high_prod_log > 1500:
                    evt_type = "max_production" if actual_prod >= 180 else "high_production"
                    _evt(agent_events, day, "ACTION", "FactoryAgent", evt_type,
                         f"[Step {day}] RL agent {'MAX' if actual_prod >= 180 else 'increased'} "
                         f"production to {actual_prod:.0f} units | Demand signal: {actual_demand:.0f}",
                         f"Production {'at full capacity' if actual_prod >= 180 else 'scaled up'}: "
                         f"{actual_prod:.0f} units ordered. RL Q-agent responding to "
                         f"{'critical inventory pressure' if actual_prod >= 180 else 'elevated demand forecast'} "
                         f"({actual_demand:.0f} units expected). "
                         f"Proactive inventory build to absorb potential surge or disruption.",
                         {"production": round(actual_prod), "demand": round(actual_demand),
                          "inventory": round(env.inventory),
                          "q_action": action_idx, "epsilon": round(rl_agent.epsilon, 3)})
                    last_high_prod_log = day

                # FulfillmentAgent: delivery confirmed (sampled every 2000 steps)
                if last_mile_result.get("delivered") and day % 2000 == 0:
                    _evt(agent_events, day, "ACTION", "FulfillmentAgent", "delivery_confirmed",
                         f"[Step {day}] Last-mile delivery: {last_mile_result['units']:.0f} units "
                         f"dispatched to customer",
                         f"Customer delivery confirmed via last-mile agent. "
                         f"{last_mile_result['units']:.0f} units fulfilled. "
                         f"Route: {last_mile_result.get('route', 'standard')}.",
                         last_mile_result)

                # Multi-warehouse branch decisions
                if use_multi_warehouse and branch != "A":
                    _evt(agent_events, day, "ACTION", "DistributionHubAgent",
                         f"branch_{branch}_routing",
                         f"[Step {day}] Distribution Hub: Branch {branch} routing — "
                         f"{'transfer: ' + str(round(transfer)) + ' units' if branch == 'B' else 'external sourcing'}",
                         (f"Inventory routed via Branch {branch}. "
                          + (f"Inter-warehouse transfer of {transfer:.0f} units initiated."
                             if branch == "B"
                             else "All warehouses depleted — SupplierDiscoveryAgent activated.")),
                         {"branch": branch, "transfer_units": round(transfer, 1), "step": day})

                # SLA breach / restore
                if step_fill < SLA_FILL_RATE and not sla_failing:
                    _evt(agent_events, day, "ALERT", "System", "sla_breach",
                         f"[Step {day}] SLA BREACH: fill rate {step_fill:.3f} below target {SLA_FILL_RATE}",
                         f"Service Level Agreement breached: Per-step fill rate at "
                         f"{step_fill:.3f}, below the {SLA_FILL_RATE} SLA floor. "
                         f"Root cause: active disruption(s): {list(curr_disp) or 'demand spike'}. "
                         f"System is working to recover — monitor inventory and production response.",
                         {"fill_rate": round(step_fill, 4), "sla": SLA_FILL_RATE,
                          "active_disruptions": list(curr_disp)})
                    sla_failing = True

                elif step_fill >= SLA_FILL_RATE and sla_failing:
                    _evt(agent_events, day, "RESOLVED", "System", "sla_restored",
                         f"[Step {day}] SLA RESTORED: fill rate recovered to {step_fill:.3f}",
                         f"Service Level Agreement restored: Fill rate back above "
                         f"{SLA_FILL_RATE} at {step_fill:.3f}. RL agent successfully "
                         f"recovered from stress event. Supply chain stability re-established "
                         f"— continuing to monitor for secondary disruptions.",
                         {"fill_rate": round(step_fill, 4), "sla": SLA_FILL_RATE})
                    sla_failing = False

                # Periodic system checkpoint
                if day - last_periodic >= 5000:
                    ep_fr = sum(fill_per_step) / max(len(fill_per_step), 1)
                    _evt(agent_events, day, "INFO", "System", "checkpoint",
                         f"[Step {day}] Checkpoint — Inventory: {env.inventory:.0f}  "
                         f"Fill rate: {ep_fr:.3f}  Disruptions: {len(curr_disp)}  "
                         f"ε: {rl_agent.epsilon:.3f}",
                         f"System health at step {day}: Inventory {env.inventory:.0f} units | "
                         f"Cumulative fill rate {ep_fr:.3f} "
                         f"({'above' if ep_fr >= SLA_FILL_RATE else 'BELOW'} SLA) | "
                         f"{len(curr_disp)} active disruption(s) | "
                         f"RL exploration rate ε={rl_agent.epsilon:.3f} | "
                         f"Total events logged: {len(agent_events)}.",
                         {"inventory": round(env.inventory),
                          "running_fill_rate": round(ep_fr, 4),
                          "epsilon": round(rl_agent.epsilon, 3),
                          "active_disruptions": len(curr_disp)})
                    last_periodic = day

        # ── Episode end ────────────────────────────────────────────────────────
        rl_agent.epsilon = max(0.01, rl_agent.epsilon * 0.97)

        ep_m = compute_metrics(costs, demands, satisfied_list)
        episode_rewards.append(total_reward)
        episode_fill_rates.append(ep_m["Fill Rate"])
        episode_avg_delays.append(ep_m["Avg Delay"])

        # BUG 3 FIX: Save full per-step costs (not just delay component)
        last_costs         = costs
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
                dqn_info = f" | buf:{diag['buffer_size']} loss:{diag['avg_loss_recent']}"
            print(f"Ep {ep+1:3d} | Reward:{total_reward:10.2f} | "
                  f"Fill:{ep_m['Fill Rate']:.3f} | Delay:{ep_m['Avg Delay']:.2f} | "
                  f"ε:{rl_agent.epsilon:.3f}{dqn_info}")

    # ── Post-training ──────────────────────────────────────────────────────────
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

    # BUG 3 FIX: Use last_costs (full cost from env.step()) not last_delay_costs
    final_metrics = compute_metrics(last_costs, last_demands, last_satisfied)

    # BUG 4 FIX: Pass only last episode's disruption events to resilience metrics.
    # Previously the full cross-episode log (~82K entries) was passed, causing
    # every step to appear disrupted (all step numbers repeat across episodes).
    last_episode_disruption_log = engine.disruption_log[last_episode_disruption_start:]
    resilience_metrics = compute_resilience_metrics(
        last_fill_per_step, last_episode_disruption_log, len(last_fill_per_step)
    )

    print("\nFinal Metrics:")
    for k, v in final_metrics.items():
        print(f"  {k}: {round(v, 3)}")

    # BUG 6 FIX: Downsample large arrays before passing to matplotlib.
    # 182K-point plots cause slow/hanging renders. 2000 points is plenty for visualization.
    print("\nGenerating plots...")
    plot_learning_curve(episode_rewards)
    plot_demand_vs_supply(
        _downsample(last_demands),
        _downsample(last_satisfied),
    )
    plot_inventory_levels(
        _downsample(last_inventory),
        last_episode_disruption_log,
    )
    plot_disruption_timeline(
        last_episode_disruption_log,
        _downsample(last_fill_per_step),
        _downsample(last_demands),
        _downsample(last_satisfied),
    )
    plot_cost_breakdown(
        _downsample(last_prod_costs),
        _downsample(last_hold_costs),
        _downsample(last_delay_costs),
    )
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
         "throughput_norm":  resilience_metrics["fill_during_disruption"]},
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
        agent_logs          = agent_events,
        sla                 = {"fill_rate": SLA_FILL_RATE, "avg_delay": SLA_AVG_DELAY},
        rl_meta             = rl_meta,
    )

    return rl_agent 