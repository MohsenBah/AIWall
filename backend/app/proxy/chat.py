"""Forward chat completion requests to upstream providers."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Mapping

import httpx
from fastapi import HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from app.audit.helpers import log_proxy_event, measure_input_length, new_request_id
from app.audit.writer import AuditWriter
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
    def __init__(
        self,
        config: AIWallConfig,
        http_client: httpx.AsyncClient,
        audit_writer: AuditWriter,
    ):
        self._config = config
        self._http_client = http_client
        self._audit_writer = audit_writer

    async def forward(self, request: Request) -> Response | StreamingResponse:
        body = await request.body()
        model = extract_model_from_body(body)
        provider = select_provider(self._config, model)
        upstream_url = build_chat_completions_url(provider)
        incoming_headers = _filter_forward_headers(request.headers)
        upstream_headers = build_upstream_headers(provider, incoming_headers)
        request_id = new_request_id()
        input_length = measure_input_length(body)
        started = time.perf_counter()

        if _request_is_streaming(body):
            return await self._forward_stream(
                request_id=request_id,
                provider_name=provider.name,
                model=model,
                body=body,
                input_length=input_length,
                upstream_url=upstream_url,
                upstream_headers=upstream_headers,
                started=started,
            )

        try:
            upstream_response = await self._http_client.post(
                upstream_url,
                content=body,
                headers=upstream_headers,
            )
        except httpx.RequestError as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            log_proxy_event(
                self._audit_writer,
                self._config,
                request_id=request_id,
                provider_name=provider.name,
                model=model,
                decision="error",
                reason="upstream_unreachable",
                input_length=input_length,
                output_length=0,
                latency_ms=latency_ms,
                body=body,
            )
            raise HTTPException(
                status_code=502,
                detail=f"Upstream provider unreachable at {upstream_url}: {exc}",
            ) from exc

        latency_ms = (time.perf_counter() - started) * 1000.0
        output_length = len(upstream_response.content)
        decision = "allow" if upstream_response.status_code < 400 else "error"
        reason = "proxied" if upstream_response.status_code < 400 else "upstream_error"

        log_proxy_event(
            self._audit_writer,
            self._config,
            request_id=request_id,
            provider_name=provider.name,
            model=model,
            decision=decision,
            reason=reason,
            input_length=input_length,
            output_length=output_length,
            latency_ms=latency_ms,
            body=body,
            response_text=upstream_response.text if upstream_response.status_code < 400 else None,
        )

        return Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            media_type=upstream_response.headers.get("content-type", "application/json"),
        )

    async def _forward_stream(
        self,
        *,
        request_id: str,
        provider_name: str,
        model: str,
        body: bytes,
        input_length: int,
        upstream_url: str,
        upstream_headers: dict[str, str],
        started: float,
    ) -> StreamingResponse | Response:
        upstream_request = self._http_client.build_request(
            "POST",
            upstream_url,
            content=body,
            headers=upstream_headers,
        )

        try:
            upstream_response = await self._http_client.send(upstream_request, stream=True)
        except httpx.RequestError as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            log_proxy_event(
                self._audit_writer,
                self._config,
                request_id=request_id,
                provider_name=provider_name,
                model=model,
                decision="error",
                reason="upstream_unreachable",
                input_length=input_length,
                output_length=0,
                latency_ms=latency_ms,
                body=body,
            )
            raise HTTPException(
                status_code=502,
                detail=f"Upstream provider unreachable at {upstream_url}: {exc}",
            ) from exc

        if upstream_response.status_code >= 400:
            error_body = await upstream_response.aread()
            latency_ms = (time.perf_counter() - started) * 1000.0
            log_proxy_event(
                self._audit_writer,
                self._config,
                request_id=request_id,
                provider_name=provider_name,
                model=model,
                decision="error",
                reason="upstream_error",
                input_length=input_length,
                output_length=len(error_body),
                latency_ms=latency_ms,
                body=body,
            )
            await upstream_response.aclose()
            return Response(
                content=error_body,
                status_code=upstream_response.status_code,
                media_type=upstream_response.headers.get("content-type", "application/json"),
            )

        output_chunks: list[bytes] = []

        async def stream_body() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream_response.aiter_bytes():
                    output_chunks.append(chunk)
                    yield chunk
            finally:
                await upstream_response.aclose()
                latency_ms = (time.perf_counter() - started) * 1000.0
                output_length = sum(len(chunk) for chunk in output_chunks)
                log_proxy_event(
                    self._audit_writer,
                    self._config,
                    request_id=request_id,
                    provider_name=provider_name,
                    model=model,
                    decision="allow",
                    reason="proxied",
                    input_length=input_length,
                    output_length=output_length,
                    latency_ms=latency_ms,
                    body=body,
                )

        return StreamingResponse(
            stream_body(),
            status_code=upstream_response.status_code,
            media_type=upstream_response.headers.get("content-type", "text/event-stream"),
        )
