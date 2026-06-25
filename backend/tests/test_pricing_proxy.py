import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import write_test_config, write_test_prices


@pytest.mark.asyncio
async def test_unknown_model_records_null_estimated_cost(tmp_path, upstream_mock_handler) -> None:
    import httpx

    from app.main import create_app

    config_path = write_test_config(tmp_path, "")
    write_test_prices(config_path)

    mock_transport = httpx.MockTransport(upstream_mock_handler)
    http_client = httpx.AsyncClient(transport=mock_transport)
    app = create_app(config_path=config_path, http_client=http_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "llama3.2:1b",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 200
    rows = app.state.audit_writer.list_recent(limit=1)
    assert rows[0].model == "llama3.2:1b"
    assert rows[0].estimated_cost is None
    await http_client.aclose()
