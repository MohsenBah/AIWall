# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.policies.conditions import evaluate_condition
from app.policies.context import PolicyContext
from app.policies.engine import PolicyEngine
from tests.conftest import write_test_config


def test_evaluate_condition_user_role_equals() -> None:
    child = PolicyContext(
        body=b"{}",
        model="gpt-4o-mini",
        input_length=1,
        user_role="child",
    )
    adult = PolicyContext(
        body=b"{}",
        model="gpt-4o-mini",
        input_length=1,
        user_role="adult",
    )
    assert evaluate_condition('user.role == "child"', child) is True
    assert evaluate_condition("user.role == 'child'", child) is True
    assert evaluate_condition('user.role == "child"', adult) is False
    assert evaluate_condition('user.role != "child"', adult) is True
    assert evaluate_condition('user.role == "child"', PolicyContext(b"{}", "m", 1)) is False


def test_evaluate_condition_user_role_and_secret() -> None:
    context = PolicyContext(
        body=b"{}",
        model="gpt-4o-mini",
        input_length=1,
        user_role="child",
        contains_secret=True,
    )
    assert (
        evaluate_condition('user.role == "child" and input.contains_secret', context) is True
    )
    assert (
        evaluate_condition(
            'user.role == "child" and input.contains_secret',
            PolicyContext(b"{}", "m", 1, user_role="adult", contains_secret=True),
        )
        is False
    )


def test_policy_engine_child_role_blocks_adult_does_not(tmp_path) -> None:
    config_path = write_test_config(
        tmp_path,
        """  - name: block-child-requests
    when: user.role == "child"
    action: block""",
    )
    engine = PolicyEngine(config_path)

    child_result = engine.evaluate(
        PolicyContext(body=b"{}", model="gpt-4o-mini", input_length=1, user_role="child")
    )
    adult_result = engine.evaluate(
        PolicyContext(body=b"{}", model="gpt-4o-mini", input_length=1, user_role="adult")
    )

    assert child_result.action == "block"
    assert child_result.policy_id == "block-child-requests"
    assert child_result.reason == "role-policy"
    assert adult_result.action == "allow"


@pytest.mark.asyncio
async def test_child_profile_matches_role_policy_adult_does_not(
    tmp_path,
    monkeypatch,
    upstream_mock_handler,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    config_path = write_test_config(
        tmp_path,
        """  - name: block-child-requests
    when: user.role == "child"
    action: block""",
        extra_yaml="""
gateway_auth:
  enabled: true
  api_key_env: AIWALL_API_KEY
""",
    )
    mock_transport = httpx.MockTransport(upstream_mock_handler)
    http_client = httpx.AsyncClient(transport=mock_transport)
    app = create_app(config_path=config_path, http_client=http_client)

    child = app.state.profile_store.create(name="Child", role="child")
    adult = app.state.profile_store.create(name="Adult", role="adult")
    child_key = app.state.profile_store.issue_api_key(child.id)
    adult_key = app.state.profile_store.issue_api_key(adult.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        child_response = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {child_key}"},
        )
        adult_response = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {adult_key}"},
        )

    assert child_response.status_code == 403
    assert child_response.json()["error"]["policy"] == "block-child-requests"
    assert adult_response.status_code == 200

    rows = app.state.audit_writer.list_recent(limit=2)
    by_user = {row.user_id: row for row in rows}
    assert by_user[str(child.id)].decision == "block"
    assert by_user[str(adult.id)].decision == "allow"
    await http_client.aclose()
