"""Optional gateway API key validation."""

from __future__ import annotations

import os
import secrets
from collections.abc import Mapping

from fastapi import HTTPException, Request

from app.config import AIWallConfig


def _extract_bearer_token(headers: Mapping[str, str]) -> str | None:
    authorization = headers.get("authorization") or headers.get("Authorization")
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def gateway_auth_enabled(config: AIWallConfig) -> bool:
    return config.gateway_auth.enabled


def validate_gateway_auth(config: AIWallConfig, request: Request) -> None:
    if not config.gateway_auth.enabled:
        return

    expected_key = os.environ.get(config.gateway_auth.api_key_env)
    if not expected_key:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Gateway auth is enabled but {config.gateway_auth.api_key_env} is not set"
            ),
        )

    provided_key = _extract_bearer_token(request.headers)
    if provided_key is None or not secrets.compare_digest(provided_key, expected_key):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing AIWall API key",
        )


def strip_client_authorization(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() != "authorization"
    }
