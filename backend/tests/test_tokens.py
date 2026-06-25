from app.proxy.tokens import estimate_token_usage, extract_token_usage


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
