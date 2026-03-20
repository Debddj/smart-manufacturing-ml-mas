def compute_reward(satisfied, demand, cost, production=0):
    """
    Tiered service bonus:
      - service >= 0.90 → +5  (target met)
      - service >= 0.95 → +3 additional (slight stretch bonus)
      - service == 1.0  → no extra reward (no incentive to over-stock
                          purely for the last few units of demand)

    Over-production penalty:
      - production beyond (demand + safety_stock) is wasteful holding cost.
        A soft penalty is applied proportional to the excess, so the agent
        learns to produce just enough rather than always maxing out.
    """

    service_level = satisfied / (demand + 1e-5)

    reward = (
        service_level * 20
        - cost * 0.005
    )

    # Tiered bonus: reward hitting the target, not exceeding it
    if service_level >= 0.90:
        reward += 5.0
    if service_level >= 0.95:
        reward += 3.0

    # Over-production penalty: anything beyond demand + safety stock (20 units)
    safety_stock = 20
    excess_production = max(0, production - (demand + safety_stock))
    reward -= excess_production * 0.05

    return reward  