# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import json
import os

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.alerts import TelegramNotifier, build_alert_dispatcher
from app.alerts.base import TRIGGER_SECRET_BLOCKED, AlertEvent
from app.config import AIWallConfig, AlertChannelConfig
from tests.conftest import write_test_config
from tests.test_secret_scanner import _random_aws_key


@pytest.mark.asyncio
async def test_telegram_notifier_posts_send_message() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        assert request.url.path.endswith("/sendMessage")
        return httpx.Response(200, json={"ok": True, "result": {}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    notifier = TelegramNotifier(
        bot_token="123456:ABC-TEST",
        chat_id="987654321",
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
    assert str(request.url) == "https://api.telegram.org/bot123456:ABC-TEST/sendMessage"
    body = json.loads(request.content.decode())
    assert body["chat_id"] == "987654321"
    assert "AIWall secret blocked" in body["text"]
    assert "block-secrets" in body["text"]
    assert "aws-access-key" in body["text"]
    await client.aclose()


@pytest.mark.asyncio
async def test_build_dispatcher_skips_telegram_without_token(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    config = AIWallConfig(
        alerts=[
            AlertChannelConfig(
                channel="telegram",
                bot_token_env="TELEGRAM_BOT_TOKEN",
                chat_id="1",
                on=["secret_blocked"],
            )
        ]
    )
    dispatcher = build_alert_dispatcher(config)
    assert dispatcher.channel_count == 0


@pytest.mark.asyncio
async def test_secret_block_sends_telegram_message(
    tmp_path,
    monkeypatch,
    upstream_mock_handler,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "999:telegram-test-token")
    config_path = write_test_config(
        tmp_path,
        """  - name: block-secrets
    when: input.contains_secret
    action: block""",
        extra_yaml="""
alerts:
  - channel: telegram
    bot_token_env: TELEGRAM_BOT_TOKEN
    chat_id: "424242"
    "on": [secret_blocked]
""".strip(),
    )

    telegram_posts: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "api.telegram.org" in str(request.url):
            telegram_posts.append(
                {
                    "url": str(request.url),
                    "body": json.loads(request.content.decode()),
                }
            )
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
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
    assert len(telegram_posts) == 1
    assert "bot999:telegram-test-token/sendMessage" in telegram_posts[0]["url"]
    text = str(telegram_posts[0]["body"]["text"])
    assert telegram_posts[0]["body"]["chat_id"] == "424242"
    assert "block-secrets" in text
    assert "secret-detected" in text
    assert secret not in text
    await http_client.aclose()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not (os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")),
    reason="Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID for a live Telegram send",
)
async def test_live_telegram_secret_block_optional() -> None:
    """Optional live check: sends a real Telegram message when env vars are set."""
    notifier = TelegramNotifier.from_env(
        bot_token_env="TELEGRAM_BOT_TOKEN",
        chat_id=os.environ["TELEGRAM_CHAT_ID"],
    )
    await notifier.send(
        AlertEvent(
            trigger=TRIGGER_SECRET_BLOCKED,
            title="AIWall live alert test",
            message="Phase 4.8 live Telegram check succeeded.",
            policy_id="block-secrets",
            reason="secret-detected",
        )
    )
