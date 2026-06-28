import pytest
from httpx import ASGITransport, AsyncClient

pytest.importorskip("jinja2")


@pytest.mark.asyncio
async def test_dashboard_renders_empty_state(tmp_path) -> None:
    import httpx

    from app.main import create_app
    from tests.conftest import write_test_config

    config_path = write_test_config(tmp_path, "")
    mock_transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    http_client = httpx.AsyncClient(transport=mock_transport)
    app = create_app(config_path=config_path, http_client=http_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Recent events" in response.text
    assert "No events yet" in response.text
    await http_client.aclose()


@pytest.mark.asyncio
async def test_dashboard_lists_recent_events(tmp_path, upstream_mock_handler) -> None:
    import httpx

    from app.main import create_app
    from tests.conftest import write_test_config

    config_path = write_test_config(tmp_path, "")
    mock_transport = httpx.MockTransport(upstream_mock_handler)
    http_client = httpx.AsyncClient(transport=mock_transport)
    app = create_app(config_path=config_path, http_client=http_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        proxied = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert proxied.status_code == 200

        response = await client.get("/")

    assert response.status_code == 200
    assert "gpt-4o-mini" in response.text
    assert "badge-allow" in response.text
    await http_client.aclose()
