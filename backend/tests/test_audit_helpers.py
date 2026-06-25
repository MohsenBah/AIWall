from app.audit.helpers import measure_input_length


def test_measure_input_length_from_messages() -> None:
    body = b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hello"}]}'
    assert measure_input_length(body) == 5


def test_measure_input_length_fallback_to_body_size() -> None:
    body = b"not-json"
    assert measure_input_length(body) == len(body)
