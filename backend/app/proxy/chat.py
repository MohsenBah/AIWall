"""Forward chat completion requests to upstream providers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping

import httpx
from fastapi import HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from app.config import AIWallConfig
from app.providers.adapters import build_chat_completions_url, build_upstream_headers
from app.providers.router import extract_model_from_body, select_provider

FORWARD_REQUEST_HEADERS = {
    "authorization",
    "content-type",
    "openai-organization",
    "openai-project",
}


def _request_is_streaming(body: bytes) -> bool:
    if not body:
        return False
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False
    return bool(payload.get("stream"))


def _filter_forward_headers(headers: Mapping[str, str]) -> dict[str, str]:
    forwarded: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in FORWARD_REQUEST_HEADERS:
            forwarded[key] = value
    return forwarded


class ChatCompletionProxy:
    def __init__(self, config: AIWallConfig, http_client: httpx.AsyncClient):
        self._config = config
        self._http_client = http_client

    async def forward(self, request: Request) -> Response | StreamingResponse:
        body = await request.body()
        model = extract_model_from_body(body)
        provider = select_provider(self._config, model)
        upstream_url = build_chat_completions_url(provider)
        incoming_headers = _filter_forward_headers(request.headers)
        upstream_headers = build_upstream_headers(provider, incoming_headers)

        if _request_is_streaming(body):
            return await self._forward_stream(upstream_url, body, upstream_headers)

        try:
            upstream_response = await self._http_client.post(
                upstream_url,
                content=body,
                headers=upstream_headers,
            )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Upstream provider unreachable at {upstream_url}: {exc}",
            ) from exc

        return Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            media_type=upstream_response.headers.get("content-type", "application/json"),
        )

    async def _forward_stream(
        self,
        upstream_url: str,
        body: bytes,
        upstream_headers: dict[str, str],
    ) -> StreamingResponse:
        upstream_request = self._http_client.build_request(
            "POST",
            upstream_url,
            content=body,
            headers=upstream_headers,
        )

        try:
            upstream_response = await self._http_client.send(upstream_request, stream=True)
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Upstream provider unreachable at {upstream_url}: {exc}",
            ) from exc

        if upstream_response.status_code >= 400:
            error_body = await upstream_response.aread()
            await upstream_response.aclose()
            return Response(
                content=error_body,
                status_code=upstream_response.status_code,
                media_type=upstream_response.headers.get("content-type", "application/json"),
            )

        async def stream_body() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream_response.aiter_bytes():
                    yield chunk
            finally:
                await upstream_response.aclose()

        return StreamingResponse(
            stream_body(),
            status_code=upstream_response.status_code,
            media_type=upstream_response.headers.get("content-type", "text/event-stream"),
        )
