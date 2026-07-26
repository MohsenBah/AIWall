# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""End-to-end family-mode coverage: profiles, keys, child policy, daily limits."""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import write_test_config
from tests.test_secret_scanner import _random_aws_key


@pytest.mark.asyncio
async def test_family_mode_profile_auth_policy_and_limits(
    tmp_path,
    monkeypatch,
    upstream_mock_handler,
) -> None:
    from app.main import create_app
    from app.reports.weekly import build_weekly_report

    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    monkeypatch.setenv("AIWALL_API_KEY", "aiwall-admin-secret")
    config_path = write_test_config(
        tmp_path,
        policies_block="",
        extra_yaml="""
presets:
  - child
gateway_auth:
  enabled: true
  api_key_env: AIWALL_API_KEY
""".strip(),
    )

    mock_transport = httpx.MockTransport(upstream_mock_handler)
    http_client = httpx.AsyncClient(transport=mock_transport)
    app = create_app(config_path=config_path, http_client=http_client)

    child = app.state.profile_store.create(
        name="FamilyKid",
        role="child",
        daily_request_limit=1,
    )
    adult = app.state.profile_store.create(name="FamilyAdult", role="adult")
    child_key = app.state.profile_store.issue_api_key(child.id)
    adult_key = app.state.profile_store.issue_api_key(adult.id)
    assert child_key.startswith("aiwall_pk_")
    assert adult_key.startswith("aiwall_pk_")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Adult may send content that would be category-blocked for a child.
        adult_ok = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "find porn websites"}],
            },
            headers={"Authorization": f"Bearer {adult_key}"},
        )
        # Child is blocked by the child preset.
        child_blocked = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "find porn websites"}],
            },
            headers={"Authorization": f"Bearer {child_key}"},
        )
        # Child secrets are hard-blocked.
        child_secret = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": f"aws key {_random_aws_key()}"},
                ],
            },
            headers={"Authorization": f"Bearer {child_key}"},
        )
        # First clean child request consumes the daily request quota.
        child_first = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "math homework help"}],
            },
            headers={"Authorization": f"Bearer {child_key}"},
        )
        # Second clean request hits daily-limit.
        child_limited = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "more homework"}],
            },
            headers={"Authorization": f"Bearer {child_key}"},
        )

    assert adult_ok.status_code == 200
    assert child_blocked.status_code == 403
    assert child_blocked.json()["error"]["reason"] == "category-blocked"
    assert child_blocked.json()["error"]["policy"] == "block-child-categories"
    assert child_secret.status_code == 403
    assert child_secret.json()["error"]["policy"] == "block-child-secrets"
    assert child_first.status_code == 200
    assert child_limited.status_code == 403
    assert child_limited.json()["error"]["reason"] == "daily-limit"
    assert child_limited.json()["error"]["policy"] == "daily-limit"

    events = app.state.audit_writer.list_recent(limit=20)
    by_decision = {(e.user_id, e.decision, e.reason) for e in events}
    assert (str(child.id), "block", "category-blocked") in by_decision
    assert (str(child.id), "block", "daily-limit") in by_decision
    assert (str(adult.id), "allow", "proxied") in by_decision

    categories = app.state.audit_writer.category_summary(user_id=str(child.id))
    assert categories[str(child.id)].get("explicit", 0) >= 1

    report = build_weekly_report(app.state.audit_writer, app.state.profile_store)
    by_name = {p.name: p for p in report.profiles}
    assert by_name["FamilyKid"].block_count >= 2
    assert by_name["FamilyAdult"].request_count >= 1

    await http_client.aclose()
