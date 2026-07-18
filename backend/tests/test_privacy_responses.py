# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.audit.helpers import privacy_safe_prompt_text
from app.main import create_app
from app.policies.engine import PolicyResult
from app.policies.responses import POLICY_ACTION_HEADER, RULE_IDS_HEADER, policy_blocked_response
from tests.conftest import write_test_config
from tests.test_secret_scanner import _random_aws_key


def test_blocked_response_includes_rule_ids_not_secret() -> None:
    secret = _random_aws_key()
    response = policy_blocked_response(
        PolicyResult(
            action="block",
            policy_id="block-secrets",
            reason="secret-detected",
            rule_ids=("aws-access-key",),
        )
    )
    body = json.loads(response.body.decode())
    payload = json.dumps(body)
    assert secret not in payload
    assert body["error"]["rule_ids"] == ["aws-access-key"]
    assert response.headers[RULE_IDS_HEADER] == "aws-access-key"
    assert response.headers[POLICY_ACTION_HEADER] == "block"


def test_privacy_safe_prompt_text_masks_secrets() -> None:
    secret = _random_aws_key()
    body = json.dumps(
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": f"key {secret}"}],
        }
    ).encode()
    prompt = privacy_safe_prompt_text(body)
    assert prompt is not None
    assert secret not in prompt
    assert "[REDACTED:aws-access-key]" in prompt


@pytest.mark.asyncio
async def test_secret_block_response_lists_rule_ids_and_hides_secret(
    tmp_path, upstream_mock_handler
) -> None:
    import httpx

    config_path = write_test_config(
        tmp_path,
        """  - name: block-secrets
    when: input.contains_secret
    action: block""",
    )
    config_path.write_text(
        config_path.read_text().replace("log_raw_prompts: false", "log_raw_prompts: true")
    )

    mock_transport = httpx.MockTransport(upstream_mock_handler)
    http_client = httpx.AsyncClient(transport=mock_transport)
    app = create_app(config_path=config_path, http_client=http_client)

    secret = _random_aws_key()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": f"my aws key is {secret}"}],
            },
        )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["rule_ids"] == ["aws-access-key"]
    assert secret not in response.text
    assert response.headers[RULE_IDS_HEADER] == "aws-access-key"

    rows = app.state.audit_writer.list_recent(limit=1)
    assert rows[0].matched_rule_ids == "aws-access-key"
    assert rows[0].raw_prompt is not None
    assert secret not in rows[0].raw_prompt
    assert "[REDACTED:aws-access-key]" in rows[0].raw_prompt
    await http_client.aclose()


@pytest.mark.asyncio
async def test_warn_secret_response_includes_rule_id_headers(
    tmp_path, upstream_mock_handler
) -> None:
    import httpx

    config_path = write_test_config(
        tmp_path,
        """  - name: warn-secrets
    when: input.contains_secret
    action: warn""",
    )
    mock_transport = httpx.MockTransport(upstream_mock_handler)
    http_client = httpx.AsyncClient(transport=mock_transport)
    app = create_app(config_path=config_path, http_client=http_client)

    secret = _random_aws_key()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": f"my aws key is {secret}"}],
            },
        )

    assert response.status_code == 200
    assert response.headers[POLICY_ACTION_HEADER] == "warn"
    assert response.headers[RULE_IDS_HEADER] == "aws-access-key"
    assert secret not in response.text

    rows = app.state.audit_writer.list_recent(limit=1)
    assert rows[0].decision == "warn"
    assert rows[0].matched_rule_ids == "aws-access-key"
    await http_client.aclose()
