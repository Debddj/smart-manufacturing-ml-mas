class SupplyChainEnvironment:

    def __init__(self):
        self.inventory = 100
        self.max_inventory = 300
        self.cost = 0

    def step(self, production, shipment, demand):

        self.inventory += production
        self.inventory = min(self.inventory, self.max_inventory)

        shipment = min(shipment, self.inventory)
        self.inventory -= shipment

        satisfied = min(shipment, demand)

        delay = max(0, demand - satisfied)

        cost = (
            production * 1.0 +
            self.inventory * 0.5 +   # was 0.1 — penalises excess stock buildup
            delay * 5
        )

        self.cost += cost

        return satisfied, cost, delay