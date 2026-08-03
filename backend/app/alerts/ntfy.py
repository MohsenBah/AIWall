# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""ntfy push alert channel (public ntfy.sh or self-hosted)."""

from __future__ import annotations

import logging

import httpx

from app.alerts.base import (
    TRIGGER_COST_THRESHOLD,
    TRIGGER_DAILY_LIMIT,
    TRIGGER_PROVIDER_ERROR,
    TRIGGER_SECRET_BLOCKED,
    AlertEvent,
)

logger = logging.getLogger(__name__)

DEFAULT_NTFY_SERVER = "https://ntfy.sh"


class NtfyNotifier:
    """Publish alerts to an ntfy topic via HTTP POST."""

    def __init__(
        self,
        *,
        topic: str,
        server: str = DEFAULT_NTFY_SERVER,
        http_client: httpx.AsyncClient | None = None,
    ):
        topic_name = topic.strip().lstrip("/")
        if not topic_name:
            raise ValueError("ntfy channel requires topic")
        base = (server or DEFAULT_NTFY_SERVER).strip().rstrip("/")
        if not base:
            raise ValueError("ntfy server must not be empty")
        if not (base.startswith("http://") or base.startswith("https://")):
            raise ValueError("ntfy server must start with http:// or https://")
        self._topic = topic_name
        self._server = base
        self._http_client = http_client

    def _publish_url(self) -> str:
        return f"{self._server}/{self._topic}"

    def _message_body(self, event: AlertEvent) -> str:
        lines = [event.message]
        if event.policy_id:
            lines.append(f"Policy: {event.policy_id}")
        if event.reason:
            lines.append(f"Reason: {event.reason}")
        if event.rule_ids:
            lines.append(f"Rules: {', '.join(event.rule_ids)}")
        if event.request_id:
            lines.append(f"Request: {event.request_id}")
        text = "\n".join(lines)
        # ntfy message bodies are typically short; keep under a safe limit.
        if len(text) > 3500:
            text = text[:3497] + "..."
        return text

    def _headers(self, event: AlertEvent) -> dict[str, str]:
        title = (event.title or "AIWall alert").strip()
        if len(title) > 200:
            title = title[:197] + "..."
        return {
            "Title": title,
            "Tags": _tags_for_trigger(event.trigger),
            "Priority": _priority_for_trigger(event.trigger),
        }

    async def send(self, event: AlertEvent) -> None:
        url = self._publish_url()
        body = self._message_body(event)
        headers = self._headers(event)
        if self._http_client is not None:
            await self._post(self._http_client, url, body, headers)
            return
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            await self._post(client, url, body, headers)

    async def _post(
        self,
        client: httpx.AsyncClient,
        url: str,
        body: str,
        headers: dict[str, str],
    ) -> None:
        response = await client.post(url, content=body.encode("utf-8"), headers=headers)
        if response.status_code >= 400:
            logger.error(
                "ntfy publish failed: url=%s status=%s body=%s",
                url,
                response.status_code,
                response.text[:500],
            )
            response.raise_for_status()


def _tags_for_trigger(trigger: str) -> str:
    if trigger == TRIGGER_SECRET_BLOCKED:
        return "warning,lock"
    if trigger == TRIGGER_PROVIDER_ERROR:
        return "x,rotating_light"
    if trigger in {TRIGGER_COST_THRESHOLD, TRIGGER_DAILY_LIMIT}:
        return "moneybag,warning"
    return "warning"


def _priority_for_trigger(trigger: str) -> str:
    # ntfy priorities: min … max / urgent; named values are accepted.
    if trigger in {TRIGGER_SECRET_BLOCKED, TRIGGER_PROVIDER_ERROR}:
        return "high"
    return "default"
