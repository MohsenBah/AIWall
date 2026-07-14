# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import secrets
import string

from app.config import EntropyScannerConfig, ScannerConfig
from app.scanners.entropy import contains_high_entropy_string, shannon_entropy
from app.scanners.secrets import SecretScanner


def _random_base64ish_token(length: int = 40) -> str:
    alphabet = string.ascii_letters + string.digits + "+/="
    return "".join(secrets.choice(alphabet) for _ in range(length))


def test_shannon_entropy_of_random_token_is_high() -> None:
    token = _random_base64ish_token()
    assert shannon_entropy(token) >= 4.5


def test_contains_high_entropy_string_flags_random_token() -> None:
    token = _random_base64ish_token(40)
    assert contains_high_entropy_string(f"value={token}", min_length=20, threshold=4.5)


def test_contains_high_entropy_string_flags_random_hex() -> None:
    token = secrets.token_hex(20)
    assert contains_high_entropy_string(f"value={token}", min_length=20, threshold=4.5)


def test_contains_high_entropy_string_ignores_normal_prose() -> None:
    text = "hello from a normal prompt about the weather today"
    assert contains_high_entropy_string(text, min_length=20, threshold=4.5) is False


def test_secret_scanner_adds_high_entropy_rule_id() -> None:
    token = _random_base64ish_token(40)
    result = SecretScanner().scan(f"token {token}")

    assert result.contains_secret is True
    assert any(match.rule_id == "high-entropy" for match in result.matches)


def test_secret_scanner_can_disable_entropy_detection() -> None:
    token = _random_base64ish_token(40)
    config = ScannerConfig(
        entropy=EntropyScannerConfig(enabled=False),
    )
    result = SecretScanner(config).scan(f"token {token}")

    assert result.contains_secret is False


def test_secret_scanner_respects_entropy_threshold() -> None:
    token = _random_base64ish_token(40)
    strict = ScannerConfig(
        entropy=EntropyScannerConfig(enabled=True, min_length=20, threshold=6.5),
    )
    result = SecretScanner(strict).scan(f"token {token}")
    assert result.contains_secret is False
