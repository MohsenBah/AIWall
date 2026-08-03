# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Pluggable alerting for notable proxy events."""

from app.alerts.base import AlertEvent, Notifier
from app.alerts.dispatcher import AlertDispatcher, build_alert_dispatcher
from app.alerts.stub import RecordingNotifier
from app.alerts.telegram import TelegramNotifier

__all__ = [
    "AlertDispatcher",
    "AlertEvent",
    "Notifier",
    "RecordingNotifier",
    "TelegramNotifier",
    "build_alert_dispatcher",
]
