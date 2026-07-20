# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import write_test_config


def _auth_config(tmp_path, *, enabled: bool = True):
    enabled_yaml = "true" if enabled else "false"
    return write_test_config(
        tmp_path,
        "",
        extra_yaml=f"""
gateway_auth:
  enabled: {enabled_yaml}
  api_key_env: AIWALL_API_KEY
""",
    )


@pytest.mark.asyncio
async def test_issue_api_key_and_attribute_audit_user_id(
    tmp_path,
    monkeypatch,
    upstream_mock_handler,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("AIWALL_API_KEY", "aiwall-admin-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    config_path = _auth_config(tmp_path)

    upstream_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        upstream_requests.append(request)
        return upstream_mock_handler(request)

    mock_transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=mock_transport)
    app = create_app(config_path=config_path, http_client=http_client)

    profile = app.state.profile_store.create(name="Kid", role="child")
    profile_key = app.state.profile_store.issue_api_key(profile.id)
    assert profile_key.startswith("aiwall_pk_")
    stored = app.state.profile_store.get(profile.id)
    assert stored is not None
    assert stored.api_key_hash is not None
    assert profile_key not in stored.api_key_hash

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {profile_key}"},
        )

    assert response.status_code == 200
    assert len(upstream_requests) == 1
    assert upstream_requests[0].headers["authorization"] == "Bearer upstream-openai-key"

    rows = app.state.audit_writer.list_recent(limit=1)
    assert rows[0].user_id == str(profile.id)
    assert rows[0].decision == "allow"
    await http_client.aclose()


@pytest.mark.asyncio
async def test_profile_key_works_without_admin_env(
    tmp_path,
    monkeypatch,
    upstream_mock_handler,
) -> None:
    from app.main import create_app

    monkeypatch.delenv("AIWALL_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    config_path = _auth_config(tmp_path)

    mock_transport = httpx.MockTransport(upstream_mock_handler)
    http_client = httpx.AsyncClient(transport=mock_transport)
    app = create_app(config_path=config_path, http_client=http_client)

    profile = app.state.profile_store.create(name="Parent", role="adult")
    profile_key = app.state.profile_store.issue_api_key(profile.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
        )
        allowed = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {profile_key}"},
        )

    assert denied.status_code == 401
    assert allowed.status_code == 200
    rows = app.state.audit_writer.list_recent(limit=1)
    assert rows[0].user_id == str(profile.id)
    await http_client.aclose()


@pytest.mark.asyncio
async def test_disabled_profile_key_is_rejected(
    tmp_path,
    monkeypatch,
    upstream_mock_handler,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    config_path = _auth_config(tmp_path)
    mock_transport = httpx.MockTransport(upstream_mock_handler)
    http_client = httpx.AsyncClient(transport=mock_transport)
    app = create_app(config_path=config_path, http_client=http_client)

    profile = app.state.profile_store.create(name="Guest", role="guest")
    profile_key = app.state.profile_store.issue_api_key(profile.id)
    app.state.profile_store.update(profile.id, enabled=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {profile_key}"},
        )

    assert response.status_code == 401
    await http_client.aclose()


@pytest.mark.asyncio
async def test_profile_key_attributes_when_gateway_auth_disabled(
    tmp_path,
    monkeypatch,
    upstream_mock_handler,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    config_path = _auth_config(tmp_path, enabled=False)
    mock_transport = httpx.MockTransport(upstream_mock_handler)
    http_client = httpx.AsyncClient(transport=mock_transport)
    app = create_app(config_path=config_path, http_client=http_client)

    profile = app.state.profile_store.create(name="Dev", role="developer")
    profile_key = app.state.profile_store.issue_api_key(profile.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {profile_key}"},
        )

    assert response.status_code == 200
    rows = app.state.audit_writer.list_recent(limit=1)
    assert rows[0].user_id == str(profile.id)
    await http_client.aclose()
