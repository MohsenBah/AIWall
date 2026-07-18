# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Forward chat completion requests to upstream providers."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Mapping

import httpx
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.audit.helpers import log_proxy_event, measure_input_length, new_request_id
from app.audit.writer import AuditWriter
from app.auth.gateway import gateway_auth_enabled, strip_client_authorization
from app.config import AIWallConfig
from app.policies.context import PolicyContext
from app.policies.engine import PolicyEngine, PolicyResult
from app.policies.responses import policy_blocked_response, privacy_safe_headers
from app.providers.adapters import build_chat_completions_url, build_upstream_headers
from app.providers.router import extract_model_from_body, select_provider
from app.proxy.tokens import (
    estimate_request_token_usage,
    extract_stream_token_usage,
    extract_token_usage,
)
from app.scanners.secrets import ScanResult, redact_request_body, scan_request_body

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


def _audit_decision(policy_result: PolicyResult, upstream_ok: bool = True) -> str:
    if policy_result.action == "redact" and upstream_ok:
        return "redact"
    if policy_result.action == "warn":
        return "warn"
    if not upstream_ok:
        return "error"
    return "allow"


def _audit_reason(policy_result: PolicyResult, upstream_reason: str | None = None) -> str:
    if policy_result.action == "redact":
        return policy_result.reason or "secret-redacted"
    if policy_result.action == "warn":
        return policy_result.reason or "policy_warn"
    return upstream_reason or "proxied"


def _policy_id_for_audit(policy_result: PolicyResult) -> str | None:
    if policy_result.action in {"warn", "redact", "block"}:
        return policy_result.policy_id
    return None


def _with_rule_ids(result: PolicyResult, scan_result: ScanResult) -> PolicyResult:
    if not scan_result.matches:
        return result
    rule_ids = tuple(match.rule_id for match in scan_result.matches)
    return PolicyResult(
        action=result.action,
        policy_id=result.policy_id,
        reason=result.reason,
        rule_ids=rule_ids,
    )


class ChatCompletionProxy:
    def __init__(
        self,
        config: AIWallConfig,
        http_client: httpx.AsyncClient,
        audit_writer: AuditWriter,
        policy_engine: PolicyEngine,
        cost_estimator,
    ):
        self._config = config
        self._http_client = http_client
        self._audit_writer = audit_writer
        self._policy_engine = policy_engine
        self._cost_estimator = cost_estimator

    def _evaluate_policy(
        self,
        body: bytes,
        provider_name: str,
        model: str,
        input_length: int,
    ) -> PolicyResult:
        scan_result = scan_request_body(body, self._config.scanners)
        projected_usage = estimate_request_token_usage(body)
        cost_estimate = self._cost_estimator.estimate(provider_name, model, projected_usage)
        context = PolicyContext(
            body=body,
            model=model,
            input_length=input_length,
            contains_secret=scan_result.contains_secret,
            estimated_cost=cost_estimate.estimated_cost if cost_estimate else 0.0,
        )
        result = self._policy_engine.evaluate(context)
        return _with_rule_ids(result, scan_result)

    async def forward(self, request: Request) -> Response | StreamingResponse | JSONResponse:
        body = await request.body()
        model = extract_model_from_body(body)
        provider = select_provider(self._config, model)
        upstream_url = build_chat_completions_url(provider)
        incoming_headers = _filter_forward_headers(request.headers)
        if gateway_auth_enabled(self._config):
            incoming_headers = strip_client_authorization(incoming_headers)
        upstream_headers = build_upstream_headers(provider, incoming_headers)
        request_id = new_request_id()
        input_length = measure_input_length(body)
        started = time.perf_counter()
        policy_result = self._evaluate_policy(body, provider.name, model, input_length)

        if policy_result.action == "block":
            latency_ms = (time.perf_counter() - started) * 1000.0
            log_proxy_event(
                self._audit_writer,
                self._config,
                request_id=request_id,
                provider_name=provider.name,
                model=model,
                decision="block",
                reason=policy_result.reason,
                input_length=input_length,
                output_length=0,
                latency_ms=latency_ms,
                body=body,
                policy_id=policy_result.policy_id,
                rule_ids=policy_result.rule_ids,
            )
            return policy_blocked_response(policy_result)

        forward_body = body
        redaction_count = 0
        if policy_result.action == "redact":
            redaction = redact_request_body(body, self._config.scanners)
            forward_body = redaction.body
            redaction_count = redaction.redaction_count
            if redaction.rule_ids and not policy_result.rule_ids:
                policy_result = PolicyResult(
                    action=policy_result.action,
                    policy_id=policy_result.policy_id,
                    reason=policy_result.reason,
                    rule_ids=redaction.rule_ids,
                )

        response_headers = privacy_safe_headers(policy_result)

        if _request_is_streaming(forward_body):
            return await self._forward_stream(
                request_id=request_id,
                provider_name=provider.name,
                model=model,
                body=forward_body,
                input_length=input_length,
                upstream_url=upstream_url,
                upstream_headers=upstream_headers,
                started=started,
                policy_result=policy_result,
                redaction_count=redaction_count,
                extra_headers=response_headers,
            )

        try:
            upstream_response = await self._http_client.post(
                upstream_url,
                content=forward_body,
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
                body=forward_body,
                policy_id=_policy_id_for_audit(policy_result),
                redaction_count=redaction_count,
                rule_ids=policy_result.rule_ids,
            )
            raise HTTPException(
                status_code=502,
                detail=f"Upstream provider unreachable at {upstream_url}: {exc}",
            ) from exc

        latency_ms = (time.perf_counter() - started) * 1000.0
        output_length = len(upstream_response.content)
        upstream_ok = upstream_response.status_code < 400
        decision = _audit_decision(policy_result, upstream_ok=upstream_ok)
        reason = _audit_reason(
            policy_result,
            "proxied" if upstream_ok else "upstream_error",
        )
        token_usage = (
            extract_token_usage(forward_body, upstream_response.content) if upstream_ok else None
        )
        cost_estimate = None
        if token_usage is not None:
            cost_estimate = self._cost_estimator.estimate(provider.name, model, token_usage)

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
            body=forward_body,
            response_text=upstream_response.text if upstream_ok else None,
            policy_id=_policy_id_for_audit(policy_result),
            prompt_tokens=token_usage.prompt_tokens if token_usage else None,
            completion_tokens=token_usage.completion_tokens if token_usage else None,
            total_tokens=token_usage.total_tokens if token_usage else None,
            estimated_cost=cost_estimate.estimated_cost if cost_estimate else None,
            redaction_count=redaction_count,
            rule_ids=policy_result.rule_ids,
        )

        return Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            media_type=upstream_response.headers.get("content-type", "application/json"),
            headers=response_headers or None,
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
        policy_result: PolicyResult,
        redaction_count: int = 0,
        extra_headers: dict[str, str] | None = None,
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
                policy_id=_policy_id_for_audit(policy_result),
                redaction_count=redaction_count,
                rule_ids=policy_result.rule_ids,
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
                policy_id=_policy_id_for_audit(policy_result),
                redaction_count=redaction_count,
                rule_ids=policy_result.rule_ids,
            )
            await upstream_response.aclose()
            return Response(
                content=error_body,
                status_code=upstream_response.status_code,
                media_type=upstream_response.headers.get("content-type", "application/json"),
                headers=extra_headers or None,
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
                output_bytes = b"".join(output_chunks)
                output_length = len(output_bytes)
                token_usage = extract_stream_token_usage(
                    body, output_bytes.decode("utf-8", errors="replace")
                )
                cost_estimate = self._cost_estimator.estimate(provider_name, model, token_usage)
                log_proxy_event(
                    self._audit_writer,
                    self._config,
                    request_id=request_id,
                    provider_name=provider_name,
                    model=model,
                    decision=_audit_decision(policy_result),
                    reason=_audit_reason(policy_result),
                    input_length=input_length,
                    output_length=output_length,
                    latency_ms=latency_ms,
                    body=body,
                    response_text=output_bytes.decode("utf-8", errors="replace"),
                    policy_id=_policy_id_for_audit(policy_result),
                    prompt_tokens=token_usage.prompt_tokens,
                    completion_tokens=token_usage.completion_tokens,
                    total_tokens=token_usage.total_tokens,
                    estimated_cost=cost_estimate.estimated_cost if cost_estimate else None,
                    redaction_count=redaction_count,
                    rule_ids=policy_result.rule_ids,
                )

        return StreamingResponse(
            stream_body(),
            status_code=upstream_response.status_code,
            media_type=upstream_response.headers.get("content-type", "text/event-stream"),
            headers=extra_headers or None,
        )
