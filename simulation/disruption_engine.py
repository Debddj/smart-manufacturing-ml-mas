import random

DISRUPTION_TYPES = {
    "supplier_failure": {
        "probability":    0.04,
        "supply_factor":  0.10,   # supply drops to 10%
        "duration_range": (3, 8),
        "description":    "Supplier failure",
        "severity":       "high",
        "color":          "red",
    },
    "demand_surge": {
        "probability":     0.06,
        "demand_factor":   2.0,   # demand doubles
        "duration_range":  (2, 5),
        "description":     "Demand surge",
        "severity":        "medium",
        "color":           "orange",
    },
    "logistics_breakdown": {
        "probability":       0.03,
        "capacity_factor":   0.20,  # logistics down to 20%
        "duration_range":    (2, 6),
        "description":       "Logistics breakdown",
        "severity":          "high",
        "color":             "blue",
    },
    "factory_slowdown": {
        "probability":         0.05,
        "production_factor":   0.40,  # production at 40%
        "duration_range":      (1, 4),
        "description":         "Factory slowdown",
        "severity":            "medium",
        "color":               "purple",
    },
}


class DisruptionEngine:
    """
    Injects stochastic supply chain disruptions into the simulation.

    At each step, every disruption type independently rolls for activation.
    Active disruptions modify the effective supply, demand, logistics capacity,
    or production before the environment processes the step.

    The RL agent is NOT told which disruption is active — it must learn
    robust policies through the signals it can observe (inventory, demand).

    Usage:
        engine = DisruptionEngine(enabled=True, seed=42)

        for day in range(n_steps):
            engine.tick(day)
            params = engine.apply(demand, supply, logistics_cap, production)
            # use params['demand'], params['supply'], etc.

        log = engine.disruption_log   # full event history
    """

    def __init__(self, enabled: bool = True, seed: int = None):
        self.enabled = enabled
        self._active: dict[str, int] = {}   # {disruption_type: remaining_steps}
        self.disruption_log: list[dict] = []
        self._step = 0
        if seed is not None:
            random.seed(seed)

    def tick(self, step: int = None):
        """Advance one simulation step. Call at the start of each day loop iteration."""
        self._step = step if step is not None else self._step + 1

        # Count down active disruptions
        expired = [k for k, v in self._active.items() if v <= 1]
        for k in expired:
            del self._active[k]
        for k in self._active:
            self._active[k] -= 1

        if not self.enabled:
            return

        # Sample new disruptions for any inactive type
        for d_type, cfg in DISRUPTION_TYPES.items():
            if d_type not in self._active and random.random() < cfg["probability"]:
                duration = random.randint(*cfg["duration_range"])
                self._active[d_type] = duration
                self.disruption_log.append({
                    "step":        self._step,
                    "type":        d_type,
                    "duration":    duration,
                    "description": cfg["description"],
                    "severity":    cfg["severity"],
                    "color":       cfg["color"],
                })

    def apply(
        self,
        demand: float,
        supply: float,
        logistics_cap: float,
        production: float,
    ) -> dict:
        """
        Return a dict of (potentially disrupted) execution parameters.
        Call after tick() each step.

        Returns keys: demand, supply, logistics_cap, production
        """
        out = {
            "demand":        demand,
            "supply":        supply,
            "logistics_cap": logistics_cap,
            "production":    production,
        }

        if "demand_surge" in self._active:
            out["demand"] *= DISRUPTION_TYPES["demand_surge"]["demand_factor"]

        if "supplier_failure" in self._active:
            out["supply"] *= DISRUPTION_TYPES["supplier_failure"]["supply_factor"]

        if "logistics_breakdown" in self._active:
            out["logistics_cap"] *= DISRUPTION_TYPES["logistics_breakdown"]["capacity_factor"]

        if "factory_slowdown" in self._active:
            out["production"] *= DISRUPTION_TYPES["factory_slowdown"]["production_factor"]

        return out

    def is_disrupted(self) -> bool:
        return bool(self._active)

    def active_types(self) -> list[str]:
        return list(self._active.keys())

    def reset(self):
        """Reset state for a new episode (keeps the log intact)."""
        self._active = {}
        self._step = 0  