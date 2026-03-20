import random

class SupplierAgent:
    """
    BUG FIXED: supply_levels [30, 50, 70] were lower than mean demand (52),
    meaning the factory could rarely produce enough to cover even average demand.
    Supply levels are updated to reflect realistic raw-material availability
    proportional to the actual demand distribution (mean=52, max=231).

    Supply represents raw-material batches available to the factory each step.
    """

    def __init__(self):
        self.supply_levels = [80, 120, 180]  # was [30, 50, 70] — too low

    def act(self):
        return random.choice(self.supply_levels)  