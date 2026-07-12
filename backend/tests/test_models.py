# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import httpx
import pytest

from app.config import ProviderConfig
from app.proxy.models import (
    _parse_ollama_models,
    _parse_openai_models,
    build_models_list_url,
    list_models,
)
from app.proxy.pricing import CostEstimator


def test_build_models_list_url_openai_compatible() -> None:
    provider = ProviderConfig(
        name="openai",
        type="openai-compatible",
        base_url="https://api.openai.com/v1",
        models=["gpt-*"],
    )
    assert build_models_list_url(provider) == "https://api.openai.com/v1/models"


def test_build_models_list_url_ollama() -> None:
    provider = ProviderConfig(
        name="ollama",
        type="ollama",
        base_url="http://127.0.0.1:11434",
        models=["llama*"],
    )
    assert build_models_list_url(provider) == "http://127.0.0.1:11434/api/tags"


def test_parse_openai_models() -> None:
    body = b'{"object":"list","data":[{"id":"gpt-4o-mini","object":"model"},{"id":"dall-e-3","object":"model"}]}'
    assert _parse_openai_models(body) == ["gpt-4o-mini", "dall-e-3"]


def test_parse_ollama_models() -> None:
    body = b'{"models":[{"name":"llama3.2:1b"},{"name":"mistral:latest"}]}'
    assert _parse_ollama_models(body) == ["llama3.2:1b", "mistral:latest"]


@pytest.mark.asyncio
async def test_list_models_filters_by_provider_patterns(tmp_path) -> None:
    from app.config import AIWallConfig
    from tests.conftest import write_test_config

    config_path = write_test_config(tmp_path, "")
    config = AIWallConfig.model_validate(
        __import__("yaml").safe_load(config_path.read_text())
    )
    prices_path = tmp_path / "prices.yaml"
    cost_estimator = CostEstimator(prices_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {"id": "gpt-4o-mini", "object": "model"},
                        {"id": "dall-e-3", "object": "model"},
                    ],
                },
            )
        if request.method == "GET" and request.url.path.endswith("/api/tags"):
            return httpx.Response(
                200,
                json={"models": [{"name": "llama3.2:1b"}, {"name": "qwen2.5"}]},
            )
        return httpx.Response(404)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    payload = await list_models(config, http_client, cost_estimator)
    await http_client.aclose()

    assert payload["object"] == "list"
    ids = [item["id"] for item in payload["data"]]
    assert "gpt-4o-mini" in ids
    assert "dall-e-3" not in ids
    assert "llama3.2:1b" in ids
    assert all(item["object"] == "model" for item in payload["data"])
    assert payload["data"][0]["owned_by"] in {"openai", "ollama"}


@pytest.mark.asyncio
async def test_list_models_falls_back_to_prices(tmp_path) -> None:
    from app.config import AIWallConfig
    from tests.conftest import write_test_config

    config_path = write_test_config(tmp_path, "")
    config = AIWallConfig.model_validate(
        __import__("yaml").safe_load(config_path.read_text())
    )
    prices_path = tmp_path / "prices.yaml"
    cost_estimator = CostEstimator(prices_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    payload = await list_models(config, http_client, cost_estimator)
    await http_client.aclose()

    ids = [item["id"] for item in payload["data"]]
    assert ids == ["gpt-4o-mini"]
