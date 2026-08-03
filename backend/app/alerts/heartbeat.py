# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Periodic provider health probes for outage alerts."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import httpx

from app.alerts.base import TRIGGER_PROVIDER_ERROR, AlertEvent
from app.alerts.dispatcher import AlertDispatcher
from app.config import AIWallConfig, ProviderConfig
from app.providers.adapters import build_upstream_headers
from app.proxy.models import build_models_list_url

logger = logging.getLogger(__name__)

PROBE_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


@dataclass
class ProviderProbeResult:
    provider: str
    ok: bool
    detail: str


@dataclass
class HeartbeatMonitor:
    """Probe configured providers and alert on healthy → unhealthy transitions."""

    config: AIWallConfig
    http_client: httpx.AsyncClient
    alert_dispatcher: AlertDispatcher | None = None
    _unhealthy: set[str] = field(default_factory=set)
    _task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def unhealthy_providers(self) -> frozenset[str]:
        return frozenset(self._unhealthy)

    async def probe_provider(self, provider: ProviderConfig) -> ProviderProbeResult:
        url = build_models_list_url(provider) or provider.base_url.rstrip("/")
        headers = build_upstream_headers(provider, {})
        try:
            response = await self.http_client.get(url, headers=headers, timeout=PROBE_TIMEOUT)
        except httpx.RequestError as exc:
            return ProviderProbeResult(
                provider=provider.name,
                ok=False,
                detail=f"unreachable: {exc}",
            )
        if response.status_code >= 500:
            return ProviderProbeResult(
                provider=provider.name,
                ok=False,
                detail=f"HTTP {response.status_code}",
            )
        return ProviderProbeResult(provider=provider.name, ok=True, detail="ok")

    async def probe_once(self) -> list[ProviderProbeResult]:
        results: list[ProviderProbeResult] = []
        for provider in self.config.providers:
            result = await self.probe_provider(provider)
            results.append(result)
            await self._handle_result(result)
        return results

    async def _handle_result(self, result: ProviderProbeResult) -> None:
        if result.ok:
            self._unhealthy.discard(result.provider)
            return
        if result.provider in self._unhealthy:
            return
        self._unhealthy.add(result.provider)
        await self._emit_outage(result)

    async def _emit_outage(self, result: ProviderProbeResult) -> None:
        if self.alert_dispatcher is None or self.alert_dispatcher.channel_count == 0:
            return
        await self.alert_dispatcher.dispatch(
            AlertEvent(
                trigger=TRIGGER_PROVIDER_ERROR,
                title="AIWall provider error",
                message=(
                    f"Heartbeat detected provider {result.provider} is down ({result.detail})."
                ),
                reason="provider_outage",
                metadata={"provider": result.provider, "detail": result.detail},
            )
        )

    def start(self) -> None:
        heartbeat = self.config.heartbeat
        if not heartbeat.enabled:
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop(), name="aiwall-heartbeat")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run_loop(self) -> None:
        interval = max(5, int(self.config.heartbeat.interval_seconds))
        logger.info("Provider heartbeat started (interval=%ss)", interval)
        try:
            while True:
                try:
                    await self.probe_once()
                except Exception:
                    logger.exception("Provider heartbeat probe failed")
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("Provider heartbeat stopped")
            raise
