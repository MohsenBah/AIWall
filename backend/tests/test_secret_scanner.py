# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
from app.scanners.secrets import SecretScanner, scan_request_body

# AWS documentation example key — safe for tests, matches detector pattern.
FAKE_AWS_KEY = "AKIAIOSFODNN7EXAMPLE"


def test_secret_scanner_detects_aws_key() -> None:
    scanner = SecretScanner()
    result = scanner.scan(f"my key is {FAKE_AWS_KEY}")

    assert result.contains_secret is True
    assert any(match.rule_id == "aws-access-key" for match in result.matches)


def test_secret_scanner_detects_github_token() -> None:
    scanner = SecretScanner()
    result = scanner.scan("token ghp_1234567890abcdefghijklmnopqrstuvwxyz")

    assert result.contains_secret is True
    assert any(match.rule_id == "github-token" for match in result.matches)


def test_secret_scanner_detects_ssh_private_key() -> None:
    scanner = SecretScanner()
    text = "-----BEGIN OPENSSH PRIVATE KEY-----\nabc"
    result = scanner.scan(text)

    assert result.contains_secret is True
    assert any(match.rule_id == "ssh-private-key" for match in result.matches)


def test_secret_scanner_ignores_clean_text() -> None:
    scanner = SecretScanner()
    result = scanner.scan("hello from a normal prompt")

    assert result.contains_secret is False
    assert result.matches == ()


def test_scan_request_body_from_chat_payload() -> None:
    body = (
        b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"key '
        + FAKE_AWS_KEY.encode()
        + b'"}]}'
    )
    result = scan_request_body(body)

    assert result.contains_secret is True
