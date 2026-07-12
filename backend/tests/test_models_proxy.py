# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_models_returns_openai_list_shape(proxy_client: AsyncClient) -> None:
    response = await proxy_client.get("/v1/models")
    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "list"
    ids = {item["id"] for item in payload["data"]}
    assert "gpt-4o-mini" in ids
    assert "llama3.2:1b" in ids
    assert all(item["object"] == "model" for item in payload["data"])
