"""Regex-based secret detection for prompts and request bodies."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SecretMatch:
    rule_id: str
    description: str


@dataclass(frozen=True)
class ScanResult:
    contains_secret: bool
    matches: tuple[SecretMatch, ...] = ()


_SECRET_RULES: tuple[tuple[str, str, str], ...] = (
    (
        "aws-access-key",
        r"\bAKIA[0-9A-Z]{16}\b",
        "AWS access key ID",
    ),
    (
        "github-token",
        r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b",
        "GitHub token",
    ),
    (
        "github-fine-grained-token",
        r"\bgithub_pat_[A-Za-z0-9_]{20,}\b",
        "GitHub fine-grained token",
    ),
    (
        "ssh-private-key",
        r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----",
        "SSH private key",
    ),
    (
        "jwt",
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
        "JSON Web Token",
    ),
    (
        "generic-api-key",
        r"(?i)(?:api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}",
        "Generic API key assignment",
    ),
    (
        "dotenv-secret",
        r"(?m)^[A-Z][A-Z0-9_]{2,}=(?:['\"]?)[^\s'\"]{8,}",
        "Environment variable secret",
    ),
)

_COMPILED_RULES = tuple(
    (rule_id, re.compile(pattern), description) for rule_id, pattern, description in _SECRET_RULES
)


class SecretScanner:
    def scan(self, text: str) -> ScanResult:
        if not text:
            return ScanResult(contains_secret=False)

        matches: list[SecretMatch] = []
        for rule_id, pattern, description in _COMPILED_RULES:
            if pattern.search(text):
                matches.append(SecretMatch(rule_id=rule_id, description=description))

        return ScanResult(contains_secret=bool(matches), matches=tuple(matches))


def scan_request_body(body: bytes) -> ScanResult:
    from app.audit.helpers import extract_prompt_text

    text = extract_prompt_text(body)
    if text is None and body:
        text = body.decode("utf-8", errors="replace")
    return SecretScanner().scan(text or "")
