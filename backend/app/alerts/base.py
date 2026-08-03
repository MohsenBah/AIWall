# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Alert event model and notifier protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# Triggers referenced by alerts[].on in aiwall.yaml
TRIGGER_SECRET_BLOCKED = "secret_blocked"
TRIGGER_POLICY_BLOCKED = "policy_blocked"
TRIGGER_COST_THRESHOLD = "cost_threshold"
TRIGGER_DAILY_LIMIT = "daily_limit"
TRIGGER_PROVIDER_ERROR = "provider_error"

KNOWN_TRIGGERS = frozenset(
    {
        TRIGGER_SECRET_BLOCKED,
        TRIGGER_POLICY_BLOCKED,
        TRIGGER_COST_THRESHOLD,
        TRIGGER_DAILY_LIMIT,
        TRIGGER_PROVIDER_ERROR,
    }
)


@dataclass(frozen=True)
class AlertEvent:
    trigger: str
    title: str
    message: str
    request_id: str | None = None
    policy_id: str | None = None
    reason: str | None = None
    rule_ids: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class Notifier(Protocol):
    """Channel adapter that delivers an alert event."""

    async def send(self, event: AlertEvent) -> None:
        """Deliver ``event``. Must not raise for routine delivery failures if possible."""
