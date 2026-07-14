# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

from app.config import RuleScannerConfig, ScannerAllowlistConfig, ScannerConfig
from app.scanners.secrets import SecretScanner

AWS_DOC_EXAMPLE = "AKIAIOSFODNN7EXAMPLE"
CORPUS_PATH = Path(__file__).resolve().parent / "fixtures" / "scanner_corpus_negative.txt"
MAX_FALSE_POSITIVE_RATE = 0.05


def _load_negative_corpus() -> list[str]:
    lines = CORPUS_PATH.read_text(encoding="utf-8").splitlines()
    return [line for line in lines if line.strip() and not line.lstrip().startswith("#")]


def test_ignore_examples_skips_aws_documentation_key() -> None:
    result = SecretScanner().scan(f"see {AWS_DOC_EXAMPLE} in the IAM guide")
    assert result.contains_secret is False


def test_ignore_examples_can_be_disabled() -> None:
    config = ScannerConfig(ignore_examples=False)
    result = SecretScanner(config).scan(f"see {AWS_DOC_EXAMPLE} in the IAM guide")
    assert result.contains_secret is True
    assert any(match.rule_id == "aws-access-key" for match in result.matches)


def test_allowlist_literal_skips_match() -> None:
    token = "demo-internal-token-abc123xyz"
    config = ScannerConfig(
        allowlist=ScannerAllowlistConfig(literals=[token]),
    )
    result = SecretScanner(config).scan(f"api_key={token}")
    assert result.contains_secret is False


def test_allowlist_pattern_skips_match() -> None:
    config = ScannerConfig(
        allowlist=ScannerAllowlistConfig(patterns=[r"^demo-"]),
    )
    result = SecretScanner(config).scan("secret_key=demo-not-a-real-secret-value")
    assert result.contains_secret is False


def test_per_rule_disable_skips_detector() -> None:
    config = ScannerConfig(
        rules={"aws-access-key": RuleScannerConfig(enabled=False)},
    )
    result = SecretScanner(config).scan("key AKIA" + ("B" * 16))
    assert result.contains_secret is False


def test_per_rule_min_length_skips_short_generic_assignment() -> None:
    config = ScannerConfig(
        rules={"generic-api-key": RuleScannerConfig(min_length=24)},
    )
    result = SecretScanner(config).scan("api_key=short-but-not-secret")
    assert result.contains_secret is False


def test_false_positive_rate_on_negative_corpus() -> None:
    corpus = _load_negative_corpus()
    scanner = SecretScanner()
    flagged = sum(1 for sample in corpus if scanner.scan(sample).contains_secret)
    fp_rate = flagged / len(corpus)

    assert len(corpus) >= 100
    assert fp_rate <= MAX_FALSE_POSITIVE_RATE, (
        f"false-positive rate {fp_rate:.1%} exceeds {MAX_FALSE_POSITIVE_RATE:.0%} "
        f"({flagged}/{len(corpus)} samples flagged)"
    )


@pytest.mark.parametrize(
    "sample",
    [
        "Use AKIAIOSFODNN7EXAMPLE when writing AWS documentation examples.",
        "Stripe docs often show sk_test_" + "0" * 24 + " as a sample value.",
        "Set api_key=EXAMPLE_KEY_FOR_DOCS_ONLY in your tutorial.",
    ],
)
def test_documentation_placeholders_are_not_flagged(sample: str) -> None:
    result = SecretScanner().scan(sample)
    assert result.contains_secret is False
