# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import json

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import write_test_config
from tests.test_secret_scanner import _random_aws_key


@pytest.mark.asyncio
async def test_redact_policy_forwards_masked_secret(
    tmp_path, upstream_mock_handler, upstream_requests
) -> None:
    import httpx

    from app.main import create_app

    config_path = write_test_config(
        tmp_path,
        """  - name: redact-secrets
    when: input.contains_secret
    action: redact""",
    )
    mock_transport = httpx.MockTransport(upstream_mock_handler)
    http_client = httpx.AsyncClient(transport=mock_transport)
    app = create_app(config_path=config_path, http_client=http_client)

    aws_key = _random_aws_key()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": f"my aws key is {aws_key}"}],
            },
        )

    assert response.status_code == 200
    assert len(upstream_requests) == 1
    forwarded = json.loads(upstream_requests[0].content.decode())
    content = forwarded["messages"][0]["content"]
    assert aws_key not in content
    assert "[REDACTED:aws-access-key]" in content

    rows = app.state.audit_writer.list_recent(limit=1)
    assert rows[0].decision == "redact"
    assert rows[0].policy_id == "redact-secrets"
    assert rows[0].reason == "secret-detected"
    assert rows[0].redaction_count > 0
    await http_client.aclose()
