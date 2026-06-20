"""Resolve upstream OpenAI-compatible provider targets."""

from __future__ import annotations

import os
from urllib.parse import urljoin

from fastapi import HTTPException

from app.config import AIWallConfig, ProviderConfig

OPENAI_COMPATIBLE = "openai-compatible"


def select_openai_compatible_provider(config: AIWallConfig) -> ProviderConfig:
    for provider in config.providers:
        if provider.type == OPENAI_COMPATIBLE:
            return provider
    raise HTTPException(
        status_code=503,
        detail="No openai-compatible provider configured",
    )


def build_chat_completions_url(provider: ProviderConfig) -> str:
    base_url = provider.base_url.rstrip("/") + "/"
    return urljoin(base_url, "chat/completions")


def build_upstream_headers(
    provider: ProviderConfig,
    incoming_headers: dict[str, str],
) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}

    authorization = incoming_headers.get("authorization") or incoming_headers.get("Authorization")
    if authorization:
        headers["Authorization"] = authorization
    elif provider.api_key_env:
        api_key = os.environ.get(provider.api_key_env)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    return headers
