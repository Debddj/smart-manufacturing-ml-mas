"""
automations/telegram_alerts.py

Telegram notification automation for Supply Chain MAS.
Sends logistics dispatch alerts via the Telegram Bot API.

Trigger: LogisticsAgent._execute() after loading goods for shipment.

.ENV variables required:
    TELEGRAM_BOT_TOKEN  — Bot token from @BotFather
    TELEGRAM_CHAT_ID    — Recipient chat / user ID
"""

from __future__ import annotations

import datetime
import os
from typing import Optional

import requests


class TelegramAlert:
    """
    Sends real-time logistics alerts to a Telegram chat via the Bot API.

    Credentials are read from environment variables (TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID) — set these in your .env file.
    """

    API_BASE = "https://api.telegram.org"
    TIMEOUT = 10  # seconds

    def __init__(self) -> None:
        self._token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # ── Public methods ────────────────────────────────────────────────────────

    def send_logistics_alert(
        self,
        order_id: str,
        units: float,
        destination: str,
    ) -> bool:
        """
        Send a logistics dispatch alert to the configured Telegram chat.

        Args:
            order_id:    Unique order identifier.
            units:       Number of units being dispatched.
            destination: Delivery destination (e.g. "Distribution Hub Kolkata").

        Returns:
            True if the message was sent successfully, False otherwise.
        """
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        message = (
            f"🚚 <b>Logistics Dispatch Alert</b>\n"
            f"Order ID: <code>{order_id}</code>\n"
            f"Units: <b>{units:.0f}</b>\n"
            f"Destination: {destination}\n"
            f"Status: <b>EN ROUTE TO DISTRIBUTION HUB</b>\n"
            f"Time: {ts}"
        )

        print(f"[TELEGRAM] Sending logistics alert for order {order_id} | Units: {units}")

        if not self._token or not self._chat_id:
            print("[TELEGRAM] [ERROR] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in .env")
            return False

        url = f"{self.API_BASE}/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": message,
            "parse_mode": "HTML",
        }

        try:
            response = requests.post(url, json=payload, timeout=self.TIMEOUT)
            response.raise_for_status()
            result = response.json()

            if result.get("ok"):
                print(f"[TELEGRAM] [OK] Alert sent - message_id: {result['result']['message_id']}")
                return True
            else:
                print(f"[TELEGRAM] [ERROR] API returned ok=false: {result}")
                return False

        except requests.exceptions.Timeout:
            print(f"[TELEGRAM] [ERROR] Request timed out after {self.TIMEOUT}s")
            return False
        except requests.exceptions.RequestException as exc:
            print(f"[TELEGRAM] [ERROR] Request failed: {exc}")
            return False
        except Exception as exc:
            print(f"[TELEGRAM] [ERROR] Unexpected error: {exc}")
            return False

    def send_custom_message(self, text: str) -> bool:
        """
        Send an arbitrary HTML-formatted message to the configured chat.

        Args:
            text: HTML-formatted message text.

        Returns:
            True on success, False on failure.
        """
        if not self._token or not self._chat_id:
            print("[TELEGRAM] [ERROR] Credentials not configured.")
            return False

        url = f"{self.API_BASE}/bot{self._token}/sendMessage"
        payload = {"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"}

        try:
            response = requests.post(url, json=payload, timeout=self.TIMEOUT)
            response.raise_for_status()
            print("[TELEGRAM] [OK] Custom message sent.")
            return True
        except Exception as exc:
            print(f"[TELEGRAM] [ERROR] {exc}")
            return False
