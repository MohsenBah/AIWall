# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.alerts import NtfyNotifier, build_alert_dispatcher
from app.alerts.base import TRIGGER_SECRET_BLOCKED, AlertEvent
from app.config import AIWallConfig, AlertChannelConfig
from tests.conftest import write_test_config
from tests.test_secret_scanner import _random_aws_key


@pytest.mark.asyncio
async def test_ntfy_notifier_posts_to_topic() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"id": "abc"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    notifier = NtfyNotifier(
        topic="aiwall-alerts",
        server="https://ntfy.example.local",
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
    assert str(request.url) == "https://ntfy.example.local/aiwall-alerts"
    assert request.headers["Title"] == "AIWall secret blocked"
    assert "lock" in request.headers["Tags"]
    assert request.headers["Priority"] == "high"
    body = request.content.decode()
    assert "block-secrets" in body
    assert "aws-access-key" in body
    await client.aclose()


def test_ntfy_defaults_to_public_server() -> None:
    notifier = NtfyNotifier(topic="home-aiwall")
    assert notifier._publish_url() == "https://ntfy.sh/home-aiwall"


def test_ntfy_requires_topic() -> None:
    with pytest.raises(ValueError, match="topic"):
        NtfyNotifier(topic="  ")


@pytest.mark.asyncio
async def test_build_dispatcher_skips_ntfy_without_topic() -> None:
    config = AIWallConfig(
        alerts=[
            AlertChannelConfig(
                channel="ntfy",
                server="https://ntfy.sh",
                on=["secret_blocked"],
            )
        ]
    )
    dispatcher = build_alert_dispatcher(config)
    assert dispatcher.channel_count == 0


@pytest.mark.asyncio
async def test_secret_block_publishes_to_ntfy(
    tmp_path,
    monkeypatch,
    upstream_mock_handler,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    ntfy_base = "https://ntfy.example.local"
    topic = "aiwall-test"
    config_path = write_test_config(
        tmp_path,
        """  - name: block-secrets
    when: input.contains_secret
    action: block""",
        extra_yaml=f"""
alerts:
  - channel: ntfy
    server: {ntfy_base}
    topic: {topic}
    "on": [secret_blocked]
""".strip(),
    )

    ntfy_posts: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(f"{ntfy_base}/"):
            ntfy_posts.append(
                {
                    "url": str(request.url),
                    "title": request.headers.get("Title"),
                    "body": request.content.decode(),
                }
            )
            return httpx.Response(200, json={"id": "1"})
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
    assert len(ntfy_posts) == 1
    assert ntfy_posts[0]["url"] == f"{ntfy_base}/{topic}"
    assert "secret" in str(ntfy_posts[0]["title"]).lower()
    assert "block-secrets" in str(ntfy_posts[0]["body"])
    assert secret not in str(ntfy_posts[0]["body"])
    await http_client.aclose()
