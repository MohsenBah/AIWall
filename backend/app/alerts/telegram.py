# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Telegram Bot API alert channel."""

from __future__ import annotations

import logging
import os

import httpx

from app.alerts.base import AlertEvent

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramNotifier:
    """Send alerts via Telegram ``sendMessage``."""

    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        http_client: httpx.AsyncClient | None = None,
        api_base: str = TELEGRAM_API_BASE,
    ):
        token = bot_token.strip()
        if not token:
            raise ValueError("Telegram bot token is required")
        chat = str(chat_id).strip()
        if not chat:
            raise ValueError("Telegram chat_id is required")
        self._bot_token = token
        self._chat_id = chat
        self._http_client = http_client
        self._api_base = api_base.rstrip("/")

    @classmethod
    def from_env(
        cls,
        *,
        bot_token_env: str,
        chat_id: str,
        http_client: httpx.AsyncClient | None = None,
        api_base: str = TELEGRAM_API_BASE,
    ) -> TelegramNotifier:
        env_name = bot_token_env.strip()
        if not env_name:
            raise ValueError("bot_token_env is required for telegram alerts")
        token = os.environ.get(env_name, "").strip()
        if not token:
            raise ValueError(f"Environment variable {env_name} is not set for telegram alerts")
        return cls(
            bot_token=token,
            chat_id=chat_id,
            http_client=http_client,
            api_base=api_base,
        )

    def _send_url(self) -> str:
        return f"{self._api_base}/bot{self._bot_token}/sendMessage"

    def _payload(self, event: AlertEvent) -> dict[str, str]:
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
        # Telegram hard limit is 4096 characters.
        if len(text) > 4000:
            text = text[:3997] + "..."
        return {"chat_id": self._chat_id, "text": text}

    async def send(self, event: AlertEvent) -> None:
        payload = self._payload(event)
        url = self._send_url()
        if self._http_client is not None:
            await self._post(self._http_client, url, payload)
            return
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            await self._post(client, url, payload)

    async def _post(
        self,
        client: httpx.AsyncClient,
        url: str,
        payload: dict[str, str],
    ) -> None:
        response = await client.post(url, json=payload)
        if response.status_code >= 400:
            logger.error(
                "Telegram sendMessage failed: status=%s body=%s",
                response.status_code,
                response.text[:500],
            )
            response.raise_for_status()
        try:
            body = response.json()
        except ValueError:
            return
        if isinstance(body, dict) and body.get("ok") is False:
            description = body.get("description") or "unknown error"
            raise RuntimeError(f"Telegram API error: {description}")
