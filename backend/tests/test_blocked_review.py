# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import pytest
from httpx import ASGITransport, AsyncClient

pytest.importorskip("jinja2")


@pytest.fixture
async def family_app(tmp_path, monkeypatch, upstream_mock_handler):
    import httpx

    from app.main import create_app
    from tests.conftest import write_test_config

    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    config_path = write_test_config(
        tmp_path,
        """  - name: block-secrets
    when: input.contains_secret
    action: block""",
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
    yield app
    await http_client.aclose()


async def _seed_blocked_events(app) -> tuple[int, int]:
    from tests.test_secret_scanner import _random_aws_key

    child = app.state.profile_store.create(name="Kiddo", role="child")
    adult = app.state.profile_store.create(name="ParentUser", role="adult")
    child_key = app.state.profile_store.issue_api_key(child.id)
    adult_key = app.state.profile_store.issue_api_key(adult.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        child_block = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "find porn websites"}],
            },
            headers={"Authorization": f"Bearer {child_key}"},
        )
        adult_block = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": f"key: {_random_aws_key()}"}],
            },
            headers={"Authorization": f"Bearer {adult_key}"},
        )
        adult_ok = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hello"}],
            },
            headers={"Authorization": f"Bearer {adult_key}"},
        )

    assert child_block.status_code == 403
    assert adult_block.status_code == 403
    assert adult_ok.status_code == 200
    return child.id, adult.id


@pytest.mark.asyncio
async def test_blocked_page_lists_all_profiles(family_app) -> None:
    await _seed_blocked_events(family_app)

    transport = ASGITransport(app=family_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get("/blocked")

    assert page.status_code == 200
    assert "Blocked events" in page.text
    assert "Kiddo" in page.text
    assert "ParentUser" in page.text
    assert "category-blocked" in page.text
    assert "secret-detected" in page.text
    # allowed events never appear on the review page
    assert "badge-allow" not in page.text


@pytest.mark.asyncio
async def test_blocked_page_filters_single_profile(family_app) -> None:
    child_id, adult_id = await _seed_blocked_events(family_app)

    transport = ASGITransport(app=family_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        child_page = await client.get("/blocked", params={"profile": str(child_id)})
        adult_page = await client.get("/blocked", params={"profile": str(adult_id)})
        unknown = await client.get("/blocked", params={"profile": "9999"})

    assert child_page.status_code == 200
    assert "Kiddo" in child_page.text
    assert "category-blocked" in child_page.text
    assert "secret-detected" not in child_page.text

    assert adult_page.status_code == 200
    assert "secret-detected" in adult_page.text
    assert "category-blocked" not in adult_page.text

    # unknown profile id falls back to showing all blocked events
    assert unknown.status_code == 200
    assert "category-blocked" in unknown.text
    assert "secret-detected" in unknown.text


@pytest.mark.asyncio
async def test_blocked_partial_renders_without_full_page(family_app) -> None:
    child_id, _ = await _seed_blocked_events(family_app)

    transport = ASGITransport(app=family_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        partial = await client.get("/partials/blocked", params={"profile": str(child_id)})
        empty = await client.get("/partials/blocked", params={"profile": ""})

    assert partial.status_code == 200
    assert "<html" not in partial.text.lower()
    assert "Kiddo" in partial.text
    assert "explicit" in partial.text

    assert empty.status_code == 200
    assert "Kiddo" in empty.text
