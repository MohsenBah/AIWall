# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Generic HTTP webhook alert channel (Discord / Slack / Home Assistant)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.alerts.base import AlertEvent

logger = logging.getLogger(__name__)


class WebhookNotifier:
    """POST a JSON alert payload to a configured URL.

    The body includes structured AIWall fields plus ``text`` (Slack) and
    ``content`` (Discord) so common incoming-webhook receivers work without
    a per-platform format switch. Home Assistant webhook triggers receive the
    full JSON body.
    """

    def __init__(
        self,
        *,
        url: str,
        http_client: httpx.AsyncClient | None = None,
    ):
        target = url.strip()
        if not target:
            raise ValueError("webhook channel requires url")
        if not (target.startswith("http://") or target.startswith("https://")):
            raise ValueError("webhook url must start with http:// or https://")
        self._url = target
        self._http_client = http_client

    def _human_text(self, event: AlertEvent) -> str:
        lines = [event.title, "", event.message]
        if event.policy_id:
            lines.append(f"Policy: {event.policy_id}")
        if event.reason:
            lines.append(f"Reason: {event.reason}")
        if event.rule_ids:
            lines.append(f"Rules: {', '.join(event.rule_ids)}")
        if event.request_id:
            lines.append(f"Request: {event.request_id}")
        text = "\n".join(lines)
        # Discord content limit is 2000; keep a margin for safety.
        if len(text) > 1900:
            text = text[:1897] + "..."
        return text

    def _payload(self, event: AlertEvent) -> dict[str, Any]:
        human = self._human_text(event)
        return {
            "source": "aiwall",
            "trigger": event.trigger,
            "title": event.title,
            "message": event.message,
            "policy_id": event.policy_id,
            "reason": event.reason,
            "rule_ids": list(event.rule_ids),
            "request_id": event.request_id,
            "metadata": dict(event.metadata),
            # Slack incoming webhooks
            "text": human,
            # Discord incoming webhooks
            "content": human,
        }

    async def send(self, event: AlertEvent) -> None:
        payload = self._payload(event)
        if self._http_client is not None:
            await self._post(self._http_client, payload)
            return
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            await self._post(client, payload)

    async def _post(self, client: httpx.AsyncClient, payload: dict[str, Any]) -> None:
        response = await client.post(
            self._url,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        if response.status_code >= 400:
            logger.error(
                "Webhook POST failed: url=%s status=%s body=%s",
                self._url,
                response.status_code,
                response.text[:500],
            )
            response.raise_for_status()
