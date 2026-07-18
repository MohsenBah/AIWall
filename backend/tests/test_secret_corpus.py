# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

from app.scanners.secrets import SecretScanner, rule_catalog, supported_rule_ids
from tests.fixtures.scanner_corpus_positive import POSITIVE_SAMPLES

NEGATIVE_CORPUS_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "scanner_corpus_negative.txt"
)
MAX_FALSE_POSITIVE_RATE = 0.05


def _load_negative_corpus() -> list[str]:
    lines = NEGATIVE_CORPUS_PATH.read_text(encoding="utf-8").splitlines()
    return [line for line in lines if line.strip() and not line.lstrip().startswith("#")]


def test_positive_corpus_covers_every_supported_rule() -> None:
    missing = set(supported_rule_ids()) - set(POSITIVE_SAMPLES)
    assert not missing, f"positive corpus missing samples for: {sorted(missing)}"


def test_rule_catalog_matches_supported_rule_ids() -> None:
    catalog_ids = [rule_id for rule_id, _ in rule_catalog()]
    assert tuple(catalog_ids) == supported_rule_ids()


@pytest.mark.parametrize("rule_id", list(supported_rule_ids()))
def test_positive_corpus_triggers_each_rule(rule_id: str) -> None:
    text = POSITIVE_SAMPLES[rule_id]()
    result = SecretScanner().scan(text)
    assert result.contains_secret is True
    assert any(match.rule_id == rule_id for match in result.matches), (
        f"{rule_id} not found in matches {[m.rule_id for m in result.matches]} "
        f"for sample {text!r}"
    )


def test_negative_corpus_false_positive_rate() -> None:
    corpus = _load_negative_corpus()
    scanner = SecretScanner()
    flagged = [sample for sample in corpus if scanner.scan(sample).contains_secret]
    fp_rate = len(flagged) / len(corpus)

    assert len(corpus) >= 100
    assert fp_rate <= MAX_FALSE_POSITIVE_RATE, (
        f"false-positive rate {fp_rate:.1%} exceeds {MAX_FALSE_POSITIVE_RATE:.0%} "
        f"({len(flagged)}/{len(corpus)}). Flagged samples: {flagged[:5]!r}"
    )
