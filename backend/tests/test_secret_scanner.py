# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import pytest

from app.scanners.secrets import SecretScanner, scan_request_body

# AWS documentation example key — safe for tests, matches detector pattern.
FAKE_AWS_KEY = "AKIAIOSFODNN7EXAMPLE"


def _fake_slack_token() -> str:
    # Assembled at runtime to avoid push-protection false positives in source.
    return "slack " + "-".join(["xoxb", "0" * 11, "0" * 12, "X" * 24])


def _fake_stripe_secret_key() -> str:
    return "stripe sk_test_" + ("0" * 24)


def _fake_stripe_restricted_key() -> str:
    return "stripe rk_test_" + ("0" * 24)


def _fake_google_api_key() -> str:
    return "google AIza" + ("EXAMPLE" + "0" * 28)


def _fake_azure_storage_key() -> str:
    return "azure AccountKey=" + ("A" * 44)


def _fake_gcp_service_account() -> str:
    return 'gcp {"type": "service_account", "project_id": "demo"}'


def _fake_database_url() -> str:
    return "db postgres://dbuser:dbpass@127.0.0.1:5432/app"


def _fake_pkcs8_private_key() -> str:
    return "key -----BEGIN PRIVATE KEY-----\nabc"


def _fake_encrypted_private_key() -> str:
    return "key -----BEGIN ENCRYPTED PRIVATE KEY-----\nabc"


_RULE_SAMPLES = {
    "slack-token": _fake_slack_token,
    "stripe-secret-key": _fake_stripe_secret_key,
    "stripe-restricted-key": _fake_stripe_restricted_key,
    "google-api-key": _fake_google_api_key,
    "azure-storage-key": _fake_azure_storage_key,
    "gcp-service-account": _fake_gcp_service_account,
    "database-url": _fake_database_url,
    "pkcs8-private-key": _fake_pkcs8_private_key,
    "encrypted-private-key": _fake_encrypted_private_key,
}


def test_secret_scanner_detects_aws_key() -> None:
    scanner = SecretScanner()
    result = scanner.scan(f"my key is {FAKE_AWS_KEY}")

    assert result.contains_secret is True
    assert any(match.rule_id == "aws-access-key" for match in result.matches)


def test_secret_scanner_detects_github_token() -> None:
    scanner = SecretScanner()
    result = scanner.scan("token ghp_" + ("0" * 36))

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


@pytest.mark.parametrize("rule_id", list(_RULE_SAMPLES))
def test_secret_scanner_detects_expanded_rule_pack(rule_id: str) -> None:
    text = _RULE_SAMPLES[rule_id]()
    result = SecretScanner().scan(text)

    assert result.contains_secret is True
    assert any(match.rule_id == rule_id for match in result.matches)
    assert all(match.rule_id for match in result.matches)
