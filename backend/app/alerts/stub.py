# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""In-memory notifier for tests and local dry-runs."""

from __future__ import annotations

from app.alerts.base import AlertEvent


class RecordingNotifier:
    """Captures alert events instead of sending them."""

    def __init__(self) -> None:
        self.events: list[AlertEvent] = []

    async def send(self, event: AlertEvent) -> None:
        self.events.append(event)

    def clear(self) -> None:
        self.events.clear()
