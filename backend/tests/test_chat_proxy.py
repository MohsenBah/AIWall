import json

import httpx
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_chat_completions_non_streaming_passthrough(
    proxy_client: AsyncClient,
    upstream_requests: list[httpx.Request],
) -> None:
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": False,
    }

    response = await proxy_client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"Authorization": "Bearer client-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "chat-1"
    assert body["choices"][0]["message"]["content"] == "hello"

    assert len(upstream_requests) == 1
    upstream = upstream_requests[0]
    assert upstream.method == "POST"
    assert upstream.url.path.endswith("/chat/completions")
    assert upstream.headers["authorization"] == "Bearer client-key"
    assert json.loads(upstream.content.decode()) == payload


@pytest.mark.asyncio
async def test_chat_completions_streaming_passthrough(
    proxy_client: AsyncClient,
    upstream_requests: list[httpx.Request],
) -> None:
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
    }

    response = await proxy_client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert b"data: [DONE]" in response.content

    assert len(upstream_requests) == 1
    assert json.loads(upstream_requests[0].content.decode())["stream"] is True


@pytest.mark.asyncio
async def test_chat_completions_requires_openai_compatible_provider(
    proxy_client_no_provider: AsyncClient,
) -> None:
    response = await proxy_client_no_provider.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "No openai-compatible provider configured"


@pytest.mark.asyncio
async def test_chat_completions_upstream_error_is_passthrough(
    example_config,
) -> None:
    def error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "invalid key", "type": "invalid_request_error"}},
        )

    mock_transport = httpx.MockTransport(error_handler)
    http_client = httpx.AsyncClient(transport=mock_transport)
    from httpx import ASGITransport, AsyncClient as TestClient

    from app.main import create_app

    app = create_app(config_path=example_config, http_client=http_client)
    transport = ASGITransport(app=app)
    async with TestClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
        )

        assert response.status_code == 401
        assert response.json()["error"]["message"] == "invalid key"

    await http_client.aclose()
