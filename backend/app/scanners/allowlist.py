# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Allowlist and documentation-placeholder handling for secret scanning."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from app.config import ScannerAllowlistConfig

_DOCUMENTATION_LITERALS: frozenset[str] = frozenset(
    {
        "AKIAIOSFODNN7EXAMPLE",
    }
)

_PLACEHOLDER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)example"),
    re.compile(r"(?i)^(?:sk_test_|rk_test_)"),
    re.compile(r"^xox[abprsb]-"),
)


def _is_repetitive_filler(value: str) -> bool:
    alnum = re.sub(r"[^A-Za-z0-9]", "", value)
    if len(alnum) < 8:
        return False
    counts = Counter(alnum.lower())
    most_common = counts.most_common(1)[0][1]
    return most_common / len(alnum) >= 0.85


def _is_test_key_placeholder(value: str) -> bool:
    for prefix in ("sk_test_", "rk_test_"):
        if value.lower().startswith(prefix):
            suffix = value[len(prefix) :]
            if suffix and len(set(suffix)) <= 2:
                return True
    if re.match(r"^xox[abprsb]-", value, re.IGNORECASE):
        alnum = re.sub(r"[^A-Za-z0-9]", "", value.lower())
        if alnum and len(set(alnum)) <= 3:
            return True
    return False


def is_documentation_placeholder(value: str) -> bool:
    if value in _DOCUMENTATION_LITERALS:
        return True
    if re.search(r"(?i)example", value):
        return True
    if _is_test_key_placeholder(value):
        return True
    if any(pattern.search(value) for pattern in _PLACEHOLDER_PATTERNS):
        if _is_repetitive_filler(value):
            return True
    return False


@dataclass
class AllowlistChecker:
    ignore_examples: bool = True
    allowlist: ScannerAllowlistConfig = field(default_factory=ScannerAllowlistConfig)
    _compiled_patterns: tuple[re.Pattern[str], ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._compiled_patterns = tuple(
            re.compile(pattern) for pattern in self.allowlist.patterns
        )

    def is_allowed(self, value: str) -> bool:
        if not value:
            return False
        if self.ignore_examples and is_documentation_placeholder(value):
            return True
        if value in self.allowlist.literals:
            return True
        return any(pattern.search(value) for pattern in self._compiled_patterns)
