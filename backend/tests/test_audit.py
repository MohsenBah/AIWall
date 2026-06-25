import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_chat_completions_writes_audit_row(
    proxy_client: AsyncClient,
    proxy_app,
) -> None:
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": False,
    }

    response = await proxy_client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200

    audit_writer = proxy_app.state.audit_writer
    rows = audit_writer.list_recent(limit=1)
    assert len(rows) == 1

    row = rows[0]
    assert row.provider == "openai"
    assert row.model == "gpt-4o-mini"
    assert row.decision == "allow"
    assert row.reason == "proxied"
    assert row.input_length == len("hello")
    assert row.output_length > 0
    assert row.latency_ms >= 0
    assert row.raw_prompt is None


@pytest.mark.asyncio
async def test_streaming_chat_completions_writes_audit_row(
    proxy_client: AsyncClient,
    proxy_app,
) -> None:
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
    }

    response = await proxy_client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    assert b"data: [DONE]" in response.content

    audit_writer = proxy_app.state.audit_writer
    rows = audit_writer.list_recent(limit=1)
    assert len(rows) == 1
    assert rows[0].decision == "allow"
    assert rows[0].output_length > 0
