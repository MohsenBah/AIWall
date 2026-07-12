# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Token usage extraction from provider responses."""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.audit.helpers import measure_input_length


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


def _chars_to_tokens(char_count: int) -> int:
    if char_count <= 0:
        return 0
    return max(1, char_count // 4)


def _completion_text_length(response_body: bytes) -> int:
    if not response_body:
        return 0
    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError:
        return len(response_body)

    choices = payload.get("choices")
    if not isinstance(choices, list):
        return len(response_body)

    total = 0
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            total += len(message["content"])
            continue
        delta = choice.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("content"), str):
            total += len(delta["content"])
    return total or len(response_body)


def estimate_token_usage(request_body: bytes, response_body: bytes) -> TokenUsage:
    prompt_chars = measure_input_length(request_body)
    completion_chars = _completion_text_length(response_body)
    prompt_tokens = _chars_to_tokens(prompt_chars)
    completion_tokens = _chars_to_tokens(completion_chars) if completion_chars else 0
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )


def _max_completion_tokens(request_body: bytes) -> int:
    if not request_body:
        return 0
    try:
        payload = json.loads(request_body)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    for key in ("max_completion_tokens", "max_tokens"):
        value = payload.get(key)
        if isinstance(value, int) and value > 0:
            return value
    return 0


def estimate_request_token_usage(request_body: bytes) -> TokenUsage:
    """Pre-request estimate: prompt from the body, completion from a max-tokens hint.

    Used to evaluate cost-based policies before forwarding, where the real
    completion size is not yet known.
    """
    prompt_tokens = _chars_to_tokens(measure_input_length(request_body))
    completion_tokens = _max_completion_tokens(request_body)
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )


def _iter_sse_payloads(sse_text: str):
    for line in sse_text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if not data or data == "[DONE]":
            continue
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            continue


def extract_stream_token_usage(request_body: bytes, sse_text: str) -> TokenUsage:
    completion_chars = 0
    for payload in _iter_sse_payloads(sse_text):
        if not isinstance(payload, dict):
            continue
        usage = payload.get("usage")
        if isinstance(usage, dict):
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            total_tokens = usage.get("total_tokens")
            if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
                if not isinstance(total_tokens, int):
                    total_tokens = prompt_tokens + completion_tokens
                return TokenUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                )
        choices = payload.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta")
                if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                    completion_chars += len(delta["content"])

    prompt_tokens = _chars_to_tokens(measure_input_length(request_body))
    completion_tokens = _chars_to_tokens(completion_chars) if completion_chars else 0
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )


def extract_token_usage(request_body: bytes, response_body: bytes) -> TokenUsage:
    if response_body:
        try:
            payload = json.loads(response_body)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            usage = payload.get("usage")
            if isinstance(usage, dict):
                prompt_tokens = usage.get("prompt_tokens")
                completion_tokens = usage.get("completion_tokens")
                total_tokens = usage.get("total_tokens")
                if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
                    if not isinstance(total_tokens, int):
                        total_tokens = prompt_tokens + completion_tokens
                    return TokenUsage(
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                    )

    return estimate_token_usage(request_body, response_body)
