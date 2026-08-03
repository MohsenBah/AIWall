# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Pluggable alerting for notable proxy events."""

from app.alerts.base import AlertEvent, Notifier
from app.alerts.dispatcher import AlertDispatcher, build_alert_dispatcher
from app.alerts.ntfy import NtfyNotifier
from app.alerts.stub import RecordingNotifier
from app.alerts.telegram import TelegramNotifier
from app.alerts.webhook import WebhookNotifier

__all__ = [
    "AlertDispatcher",
    "AlertEvent",
    "Notifier",
    "NtfyNotifier",
    "RecordingNotifier",
    "TelegramNotifier",
    "WebhookNotifier",
    "build_alert_dispatcher",
]
