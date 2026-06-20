import pytest
from httpx import AsyncClient

from app import __version__


@pytest.mark.asyncio
async def test_healthz_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"] == __version__
    assert payload["service"] == "aiwall"
    assert payload["providers"] == 2
    assert payload["policies"] == 1
