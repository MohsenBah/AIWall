# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""High-entropy string detection for unknown secret formats."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable

_BASE64ISH_TOKEN = re.compile(r"[A-Za-z0-9+/=_-]+")
_HEX_TOKEN = re.compile(r"[0-9a-fA-F]+")


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _charset_max_entropy(token: str) -> float:
    if re.fullmatch(r"[0-9a-fA-F]+", token):
        return math.log2(16)
    if re.fullmatch(r"[A-Za-z0-9+/=_-]+", token):
        return math.log2(64)
    return math.log2(len(set(token)))


def _entropy_candidates(text: str, min_length: int) -> set[str]:
    candidates: set[str] = set()
    for pattern in (_BASE64ISH_TOKEN, _HEX_TOKEN):
        for match in pattern.finditer(text):
            token = match.group()
            if len(token) >= min_length:
                candidates.add(token)
    return candidates


def contains_high_entropy_string(
    text: str,
    *,
    min_length: int = 20,
    threshold: float = 4.5,
    is_allowed: Callable[[str], bool] | None = None,
) -> bool:
    for token in _entropy_candidates(text, min_length):
        if is_allowed and is_allowed(token):
            continue
        if shannon_entropy(token) >= threshold:
            return True
        normalized = shannon_entropy(token) / _charset_max_entropy(token)
        if normalized >= 0.85 and len(token) >= min_length:
            return True
    return False
