"""
agents/regional_analytics_agent.py

Aggregates store performance data into regional metrics.
Provides data to the regional dashboard.
"""

from __future__ import annotations

import logging
from communication.message_bus import MessageBus, MessageType, Priority

logger = logging.getLogger("RegionalAnalyticsAgent")

class RegionalAnalyticsAgent:
    def __init__(self, bus: MessageBus):
        self.bus = bus
        self.bus.subscribe(MessageType.STOCK_ALERT, self.on_stock_alert)
        logger.info("RegionalAnalyticsAgent initialized.")

    def on_stock_alert(self, payload: dict) -> None:
        """
        Track alerts at the regional level.
        In a real deployment, this might aggregate alerts to detect systemic
        supply chain issues across multiple stores.
        """
        store_id = payload.get("store_id")
        alert_type = payload.get("alert_type")
        logger.info(f"RegionalAnalyticsAgent noted {alert_type} at store {store_id}.")
