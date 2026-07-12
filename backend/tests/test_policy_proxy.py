# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import write_test_config


@pytest.mark.asyncio
async def test_policy_block_returns_structured_error(tmp_path, upstream_mock_handler) -> None:
    import httpx

    from app.main import create_app

    config_path = write_test_config(
        tmp_path,
        """  - name: block-long-input
    when: input.length > 3
    action: block""",
    )
    mock_transport = httpx.MockTransport(upstream_mock_handler)
    http_client = httpx.AsyncClient(transport=mock_transport)
    app = create_app(config_path=config_path, http_client=http_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["type"] == "policy_blocked"
    assert body["error"]["policy"] == "block-long-input"

    rows = app.state.audit_writer.list_recent(limit=1)
    assert rows[0].decision == "block"
    assert rows[0].policy_id == "block-long-input"
    await http_client.aclose()


@pytest.mark.asyncio
async def test_disabled_policy_does_not_block(tmp_path, upstream_mock_handler) -> None:
    import httpx

    from app.main import create_app

    config_path = write_test_config(
        tmp_path,
        """  - name: block-long-input
    when: input.length > 3
    action: block
    enabled: false""",
    )
    mock_transport = httpx.MockTransport(upstream_mock_handler)
    http_client = httpx.AsyncClient(transport=mock_transport)
    app = create_app(config_path=config_path, http_client=http_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 200
    await http_client.aclose()
