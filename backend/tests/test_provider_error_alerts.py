# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.alerts import HeartbeatMonitor, RecordingNotifier, build_alert_dispatcher
from app.alerts.base import TRIGGER_PROVIDER_ERROR
from app.config import (
    AIWallConfig,
    AlertChannelConfig,
    HeartbeatConfig,
    ProviderConfig,
    load_config,
)
from tests.conftest import write_test_config


@pytest.mark.asyncio
async def test_upstream_unreachable_emits_provider_error(
    tmp_path,
    monkeypatch,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    config_path = write_test_config(
        tmp_path,
        """  - name: block-secrets
    when: input.contains_secret
    action: block""",
        extra_yaml="""
alerts:
  - channel: stub
    "on": [provider_error]
""".strip(),
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    recorder = RecordingNotifier()
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = create_app(
        config_path=config_path,
        http_client=http_client,
        recording_notifier=recorder,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 502
    assert len(recorder.events) == 1
    assert recorder.events[0].trigger == TRIGGER_PROVIDER_ERROR
    assert recorder.events[0].reason == "upstream_unreachable"
    assert recorder.events[0].metadata.get("provider") == "openai"
    await http_client.aclose()


@pytest.mark.asyncio
async def test_upstream_5xx_emits_provider_error(
    tmp_path,
    monkeypatch,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    config_path = write_test_config(
        tmp_path,
        policies_block="",
        extra_yaml="""
alerts:
  - channel: stub
    "on": [provider_error]
""".strip(),
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    recorder = RecordingNotifier()
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = create_app(
        config_path=config_path,
        http_client=http_client,
        recording_notifier=recorder,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 503
    assert len(recorder.events) == 1
    assert recorder.events[0].trigger == TRIGGER_PROVIDER_ERROR
    assert recorder.events[0].reason == "upstream_error"
    assert recorder.events[0].metadata.get("status_code") == "503"
    await http_client.aclose()


@pytest.mark.asyncio
async def test_upstream_4xx_does_not_emit_provider_error(
    tmp_path,
    monkeypatch,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    config_path = write_test_config(
        tmp_path,
        policies_block="",
        extra_yaml="""
alerts:
  - channel: stub
    "on": [provider_error]
""".strip(),
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    recorder = RecordingNotifier()
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = create_app(
        config_path=config_path,
        http_client=http_client,
        recording_notifier=recorder,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 401
    assert recorder.events == []
    await http_client.aclose()


@pytest.mark.asyncio
async def test_heartbeat_probe_alerts_once_on_outage() -> None:
    config = AIWallConfig(
        providers=[
            ProviderConfig(
                name="openai",
                type="openai-compatible",
                base_url="https://api.openai.com/v1",
                api_key_env="OPENAI_API_KEY",
                models=["gpt-*"],
            )
        ],
        alerts=[AlertChannelConfig(channel="stub", on=["provider_error"])],
        heartbeat=HeartbeatConfig(enabled=True, interval_seconds=60),
    )
    recorder = RecordingNotifier()
    dispatcher = build_alert_dispatcher(config, recording_notifier=recorder)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monitor = HeartbeatMonitor(
        config=config,
        http_client=http_client,
        alert_dispatcher=dispatcher,
    )

    first = await monitor.probe_once()
    second = await monitor.probe_once()

    assert first[0].ok is False
    assert second[0].ok is False
    assert "openai" in monitor.unhealthy_providers
    assert len(recorder.events) == 1
    assert recorder.events[0].trigger == TRIGGER_PROVIDER_ERROR
    assert recorder.events[0].reason == "provider_outage"
    await http_client.aclose()


@pytest.mark.asyncio
async def test_heartbeat_recovers_and_can_alert_again() -> None:
    config = AIWallConfig(
        providers=[
            ProviderConfig(
                name="openai",
                type="openai-compatible",
                base_url="https://api.openai.com/v1",
                models=["gpt-*"],
            )
        ],
        alerts=[AlertChannelConfig(channel="stub", on=["provider_error"])],
    )
    recorder = RecordingNotifier()
    dispatcher = build_alert_dispatcher(config, recording_notifier=recorder)
    fail = {"value": True}

    def handler(_request: httpx.Request) -> httpx.Response:
        if fail["value"]:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"object": "list", "data": []})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monitor = HeartbeatMonitor(
        config=config,
        http_client=http_client,
        alert_dispatcher=dispatcher,
    )

    await monitor.probe_once()
    assert len(recorder.events) == 1

    fail["value"] = False
    await monitor.probe_once()
    assert monitor.unhealthy_providers == frozenset()

    fail["value"] = True
    await monitor.probe_once()
    assert len(recorder.events) == 2
    await http_client.aclose()


def test_heartbeat_config_loads(tmp_path) -> None:
    config_path = write_test_config(
        tmp_path,
        policies_block="",
        extra_yaml="""
heartbeat:
  enabled: true
  interval_seconds: 30
""".strip(),
    )
    config = load_config(config_path)
    assert config.heartbeat.enabled is True
    assert config.heartbeat.interval_seconds == 30
