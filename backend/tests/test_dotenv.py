# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
from app.config import DotenvScannerConfig, ScannerConfig
from app.scanners.dotenv import detect_dotenv_block
from app.scanners.secrets import SecretScanner


def _sample_dotenv_body() -> str:
    return "\n".join(
        [
            "DATABASE_URL=postgres://dbuser:dbpass123@127.0.0.1:5432/app",
            "REDIS_URL=redis://cacheuser:cachepass99@127.0.0.1:6379/0",
            "OPENAI_API_KEY=sk-proj-livevalue1234567890abcd",
            "GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        ]
    )


def test_detect_dotenv_block_counts_assignments() -> None:
    detection = detect_dotenv_block(_sample_dotenv_body())
    assert detection.detected is True
    assert detection.line_count == 4


def test_detect_dotenv_block_ignores_normal_prose() -> None:
    text = "Please explain how environment variables work in Docker Compose."
    assert detect_dotenv_block(text).detected is False


def test_detect_dotenv_block_ignores_common_non_secret_keys() -> None:
    text = "\n".join(
        [
            "PATH=/usr/local/bin:/usr/bin",
            "HOME=/home/developer",
            "SHELL=/bin/bash",
        ]
    )
    assert detect_dotenv_block(text).detected is False


def test_secret_scanner_dotenv_body_triggers_with_count() -> None:
    result = SecretScanner().scan(_sample_dotenv_body())

    assert result.contains_secret is True
    dotenv_matches = [match for match in result.matches if match.rule_id == "dotenv-secret"]
    assert len(dotenv_matches) == 1
    assert dotenv_matches[0].count == 4
    assert "4 assignments" in dotenv_matches[0].description


def test_secret_scanner_single_credential_env_line() -> None:
    text = "OPENAI_API_KEY=sk-proj-livevalue1234567890abcd"
    result = SecretScanner().scan(text)

    assert result.contains_secret is True
    dotenv_matches = [match for match in result.matches if match.rule_id == "dotenv-secret"]
    assert len(dotenv_matches) == 1
    assert dotenv_matches[0].count == 1


def test_secret_scanner_large_pasted_credential_file() -> None:
    text = "\n".join(
        [
            "app.name: demo-service",
            "app.region: us-east-1",
            "database.host: db.internal",
            "database.user: app_user",
            "database.password: super-secret-password-value",
            "cache.endpoint: redis.internal:6379",
        ]
    )
    result = SecretScanner().scan(text)

    assert result.contains_secret is True
    dotenv_matches = [match for match in result.matches if match.rule_id == "dotenv-secret"]
    assert len(dotenv_matches) == 1
    assert dotenv_matches[0].count is not None
    assert dotenv_matches[0].count >= 5


def test_secret_scanner_can_disable_dotenv_heuristic() -> None:
    config = ScannerConfig(dotenv=DotenvScannerConfig(enabled=False))
    result = SecretScanner(config).scan(_sample_dotenv_body())
    assert all(match.rule_id != "dotenv-secret" for match in result.matches)


def test_secret_scanner_redacts_dotenv_lines() -> None:
    body = _sample_dotenv_body()
    result = SecretScanner().redact(body)
    assert result.redaction_count >= 4
    assert "dbpass123" not in result.text
    assert "[REDACTED:dotenv-secret]" in result.text
