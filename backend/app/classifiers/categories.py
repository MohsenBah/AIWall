# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Keyword-based prompt category classification for family policies."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Ordered by severity for primary-category selection.
CATEGORY_PRIORITY = ("explicit", "violence", "unsafe")

_CATEGORY_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "explicit": (
        re.compile(r"(?i)\b(?:porn|pornography|nude|nudes|nsfw|xxx)\b"),
        re.compile(r"(?i)\b(?:erotic|sexually explicit)\b"),
    ),
    "violence": (
        re.compile(r"(?i)\b(?:how to (?:make|build) a bomb)\b"),
        re.compile(r"(?i)\b(?:kill someone|murder (?:plan|someone)|school shooting)\b"),
        re.compile(r"(?i)\b(?:graphic violence)\b"),
    ),
    "unsafe": (
        re.compile(r"(?i)\b(?:how to (?:hack|steal)|credit card fraud)\b"),
        re.compile(r"(?i)\b(?:self[- ]harm|suicide methods?)\b"),
        re.compile(r"(?i)\b(?:buy (?:drugs|cocaine|meth))\b"),
    ),
}


@dataclass(frozen=True)
class CategoryResult:
    categories: frozenset[str]
    primary: str | None = None

    @property
    def detected(self) -> bool:
        return bool(self.categories)


def classify_text(text: str) -> CategoryResult:
    """Return matched content categories for a prompt string."""
    if not text or not text.strip():
        return CategoryResult(categories=frozenset())

    matched: set[str] = set()
    for category, patterns in _CATEGORY_PATTERNS.items():
        if any(pattern.search(text) for pattern in patterns):
            matched.add(category)

    primary = next((name for name in CATEGORY_PRIORITY if name in matched), None)
    return CategoryResult(categories=frozenset(matched), primary=primary)


def classify_request_body(body: bytes) -> CategoryResult:
    from app.audit.helpers import extract_prompt_text

    text = extract_prompt_text(body)
    if text is None and body:
        text = body.decode("utf-8", errors="replace")
    return classify_text(text or "")
