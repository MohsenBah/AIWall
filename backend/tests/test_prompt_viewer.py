# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import write_test_config

pytest.importorskip("jinja2")


def _enable_raw_prompts(config_path: Path) -> None:
    config_path.write_text(
        config_path.read_text().replace("log_raw_prompts: false", "log_raw_prompts: true")
    )


@pytest.mark.asyncio
async def test_prompt_viewer_unavailable_when_raw_logging_disabled(
    tmp_path: Path,
) -> None:
    from app.main import create_app

    config_path = write_test_config(tmp_path, "")
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    )
    app = create_app(config_path=config_path, http_client=http_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/prompts")
        dashboard = await client.get("/")

    assert missing.status_code == 404
    assert "log_raw_prompts" in missing.json()["detail"]
    assert "Prompt log" not in dashboard.text
    await http_client.aclose()


@pytest.mark.asyncio
async def test_prompt_viewer_shows_banner_and_masked_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    upstream_mock_handler,
) -> None:
    from app.main import create_app
    from tests.test_secret_scanner import _random_aws_key

    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    config_path = write_test_config(
        tmp_path,
        """  - name: warn-secrets
    when: input.contains_secret
    action: warn""",
    )
    _enable_raw_prompts(config_path)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream_mock_handler))
    app = create_app(config_path=config_path, http_client=http_client)

    secret = _random_aws_key()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        proxied = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": f"debug with key {secret} please"}
                ],
            },
        )
        assert proxied.status_code == 200

        page = await client.get("/prompts")
        rows = app.state.audit_writer.search_events(limit=1, has_raw_prompt=True)
        assert rows.total == 1
        detail = await client.get(f"/partials/prompts/{rows.events[0].id}/detail")
        dashboard = await client.get("/")

    assert page.status_code == 200
    assert "Privacy warning" in page.text
    assert "Prompt log" in page.text
    assert "debug with key" in page.text
    assert secret not in page.text
    assert "[REDACTED:aws-access-key]" in page.text
    assert "Prompt log" in dashboard.text

    assert detail.status_code == 200
    assert "Prompt" in detail.text
    assert "[REDACTED:aws-access-key]" in detail.text
    assert secret not in detail.text
    await http_client.aclose()
