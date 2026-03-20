class LogisticsAgent:

    def __init__(self):
        self.capacity = 300

    def act(self, shipment):

        return min(shipment, self.capacity)  