# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
from app.proxy.tokens import (
    estimate_request_token_usage,
    estimate_token_usage,
    extract_stream_token_usage,
    extract_token_usage,
)


def test_extract_token_usage_from_provider_response() -> None:
    request_body = b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}]}'
    response_body = b'{"choices":[{"message":{"content":"hello"}}],"usage":{"prompt_tokens":9,"completion_tokens":3,"total_tokens":12}}'

    usage = extract_token_usage(request_body, response_body)

    assert usage.prompt_tokens == 9
    assert usage.completion_tokens == 3
    assert usage.total_tokens == 12


def test_extract_token_usage_falls_back_to_heuristic() -> None:
    request_body = b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"12345678"}]}'
    response_body = b'{"choices":[{"message":{"content":"abcd"}}]}'

    usage = extract_token_usage(request_body, response_body)

    assert usage.prompt_tokens == 2
    assert usage.completion_tokens == 1
    assert usage.total_tokens == 3


def test_estimate_token_usage_without_response_usage() -> None:
    request_body = b'{"messages":[{"role":"user","content":"hello"}]}'
    response_body = b'{"choices":[{"message":{"content":"world"}}]}'

    usage = estimate_token_usage(request_body, response_body)

    assert usage.prompt_tokens >= 1
    assert usage.completion_tokens >= 1
    assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens


def test_estimate_request_token_usage_uses_max_tokens_hint() -> None:
    request_body = b'{"messages":[{"role":"user","content":"hello there"}],"max_tokens":500}'

    usage = estimate_request_token_usage(request_body)

    assert usage.prompt_tokens >= 1
    assert usage.completion_tokens == 500
    assert usage.total_tokens == usage.prompt_tokens + 500


def test_estimate_request_token_usage_without_hint() -> None:
    request_body = b'{"messages":[{"role":"user","content":"hello"}]}'

    usage = estimate_request_token_usage(request_body)

    assert usage.prompt_tokens >= 1
    assert usage.completion_tokens == 0


def test_extract_stream_token_usage_prefers_usage_chunk() -> None:
    request_body = b'{"messages":[{"role":"user","content":"hi"}]}'
    sse_text = (
        'data: {"choices":[{"delta":{"content":"he"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"llo"}}]}\n\n'
        'data: {"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":4,"total_tokens":15}}\n\n'
        "data: [DONE]\n\n"
    )

    usage = extract_stream_token_usage(request_body, sse_text)

    assert usage.prompt_tokens == 11
    assert usage.completion_tokens == 4
    assert usage.total_tokens == 15


def test_extract_stream_token_usage_falls_back_to_delta_content() -> None:
    request_body = b'{"messages":[{"role":"user","content":"hi"}]}'
    sse_text = (
        'data: {"choices":[{"delta":{"content":"abcd"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"efgh"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    usage = extract_stream_token_usage(request_body, sse_text)

    assert usage.prompt_tokens >= 1
    assert usage.completion_tokens == 2  # 8 chars / 4
    assert usage.total_tokens == usage.prompt_tokens + 2
