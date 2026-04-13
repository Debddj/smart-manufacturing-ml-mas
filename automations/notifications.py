"""
automations/notifications.py

Desktop notification automation for Supply Chain MAS.
Sends OS-level desktop notifications using the plyer library.

Trigger: Called from OrderManagementAgent after order validation.
"""

from __future__ import annotations

import datetime
from typing import Optional


def send_desktop_notification(
    title: str,
    message: str,
    timeout: int = 5,
) -> bool:
    """
    Send a desktop notification using the plyer library.

    Args:
        title:   Notification title shown in the OS banner.
        message: Body text of the notification.
        timeout: How long (seconds) the notification stays visible.

    Returns:
        True if notification was sent successfully, False otherwise.
    """
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[NOTIFICATION] [{ts}] Title: '{title}' | Message: '{message}'")

    try:
        from plyer import notification  # type: ignore
        notification.notify(
            title=title,
            message=message,
            app_name="Supply Chain MAS",
            timeout=timeout,
        )
        return True
    except Exception as exc:
        print(f"[NOTIFICATION] [ERROR] Failed to send desktop notification: {exc}")
        return False
