# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.alerts import WebhookNotifier, build_alert_dispatcher
from app.alerts.base import TRIGGER_SECRET_BLOCKED, AlertEvent
from app.config import AIWallConfig, AlertChannelConfig
from tests.conftest import write_test_config
from tests.test_secret_scanner import _random_aws_key


@pytest.mark.asyncio
async def test_webhook_notifier_posts_json_payload() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(204)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    notifier = WebhookNotifier(
        url="https://hooks.example.local/aiwall",
        http_client=client,
    )
    await notifier.send(
        AlertEvent(
            trigger=TRIGGER_SECRET_BLOCKED,
            title="AIWall secret blocked",
            message="Policy block-secrets blocked a request (secret-detected).",
            policy_id="block-secrets",
            reason="secret-detected",
            rule_ids=("aws-access-key",),
            request_id="req-1",
        )
    )

    assert len(captured) == 1
    request = captured[0]
    assert str(request.url) == "https://hooks.example.local/aiwall"
    body = json.loads(request.content.decode())
    assert body["source"] == "aiwall"
    assert body["trigger"] == TRIGGER_SECRET_BLOCKED
    assert body["policy_id"] == "block-secrets"
    assert body["rule_ids"] == ["aws-access-key"]
    assert "block-secrets" in body["text"]
    assert body["content"] == body["text"]
    await client.aclose()


def test_webhook_requires_http_url() -> None:
    with pytest.raises(ValueError, match="http"):
        WebhookNotifier(url="ftp://hooks.example.local/x")


@pytest.mark.asyncio
async def test_build_dispatcher_skips_webhook_without_url() -> None:
    config = AIWallConfig(
        alerts=[
            AlertChannelConfig(
                channel="webhook",
                on=["secret_blocked"],
            )
        ]
    )
    dispatcher = build_alert_dispatcher(config)
    assert dispatcher.channel_count == 0


@pytest.mark.asyncio
async def test_secret_block_posts_webhook_payload(
    tmp_path,
    monkeypatch,
    upstream_mock_handler,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    webhook_url = "https://ha.example.local/api/webhook/aiwall"
    config_path = write_test_config(
        tmp_path,
        """  - name: block-secrets
    when: input.contains_secret
    action: block""",
        extra_yaml=f"""
alerts:
  - channel: webhook
    url: {webhook_url}
    "on": [secret_blocked]
""".strip(),
    )

    webhook_posts: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(webhook_url):
            webhook_posts.append(
                {
                    "url": str(request.url),
                    "body": json.loads(request.content.decode()),
                }
            )
            return httpx.Response(200, json={"ok": True})
        return upstream_mock_handler(request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = create_app(config_path=config_path, http_client=http_client)
    assert app.state.alert_dispatcher.channel_count == 1

    secret = _random_aws_key()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": f"leak {secret}"}],
            },
        )

    assert response.status_code == 403
    assert len(webhook_posts) == 1
    assert webhook_posts[0]["url"] == webhook_url
    body = webhook_posts[0]["body"]
    assert body["trigger"] == TRIGGER_SECRET_BLOCKED
    assert body["policy_id"] == "block-secrets"
    assert body["reason"] == "secret-detected"
    assert secret not in json.dumps(body)
    await http_client.aclose()
