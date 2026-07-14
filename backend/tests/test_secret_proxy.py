# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.conftest import write_test_config
from tests.test_secret_scanner import _random_aws_key


@pytest.mark.asyncio
async def test_secret_in_prompt_is_blocked_and_logged(tmp_path, upstream_mock_handler) -> None:
    import httpx

    config_path = write_test_config(
        tmp_path,
        """  - name: block-secrets
    when: input.contains_secret
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
                "messages": [{"role": "user", "content": f"my aws key is {_random_aws_key()}"}],
            },
        )

    assert response.status_code == 403
    assert response.json()["error"]["policy"] == "block-secrets"

    rows = app.state.audit_writer.list_recent(limit=1)
    assert rows[0].decision == "block"
    assert rows[0].reason == "secret-detected"
    assert rows[0].policy_id == "block-secrets"
    await http_client.aclose()
