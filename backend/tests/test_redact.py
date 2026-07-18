# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import json
import secrets
import string

from app.scanners.secrets import SecretScanner, redact_request_body


def _random_aws_key() -> str:
    suffix = "".join(secrets.choice(string.digits + string.ascii_uppercase) for _ in range(16))
    return "AKIA" + suffix


def test_secret_scanner_redacts_aws_key_in_place() -> None:
    key = _random_aws_key()
    result = SecretScanner().redact(f"my key is {key}")

    assert result.redaction_count == 1
    assert key not in result.text
    assert "[REDACTED:aws-access-key]" in result.text
    assert "aws-access-key" in result.rule_ids


def test_redact_request_body_masks_chat_message_content() -> None:
    key = _random_aws_key()
    body = json.dumps(
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": f"my aws key is {key}"}],
        }
    ).encode()

    result = redact_request_body(body)

    assert result.redaction_count >= 1
    forwarded = json.loads(result.body)
    content = forwarded["messages"][0]["content"]
    assert key not in content
    assert "[REDACTED:aws-access-key]" in content


def test_redact_request_body_clean_prompt_unchanged() -> None:
    body = json.dumps(
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hello from a normal prompt"}],
        }
    ).encode()

    result = redact_request_body(body)

    assert result.redaction_count == 0
    assert result.body == body
