# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Regex-based secret detection for prompts and request bodies."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import ScannerConfig
from app.scanners.entropy import contains_high_entropy_string


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
        "slack-token",
        r"\bxox[abprsb]-[0-9A-Za-z-]{10,}\b",
        "Slack token",
    ),
    (
        "stripe-secret-key",
        r"\bsk_(?:live|test)_[0-9a-zA-Z]{16,}\b",
        "Stripe secret key",
    ),
    (
        "stripe-restricted-key",
        r"\brk_(?:live|test)_[0-9a-zA-Z]{16,}\b",
        "Stripe restricted key",
    ),
    (
        "google-api-key",
        r"\bAIza[0-9A-Za-z\-_]{35}\b",
        "Google API key",
    ),
    (
        "azure-storage-key",
        r"(?i)(?:AccountKey|SharedAccessKey)=['\"]?[A-Za-z0-9+/=]{40,}",
        "Azure storage access key",
    ),
    (
        "gcp-service-account",
        r'"type"\s*:\s*"service_account"',
        "GCP service account JSON",
    ),
    (
        "database-url",
        (
            r"(?i)(?:postgres|postgresql|mysql|mongodb(?:\+srv)?|redis)"
            r"://[^\s:@/]+:[^\s@/]+@"
        ),
        "Database connection URL with credentials",
    ),
    (
        "ssh-private-key",
        r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )PRIVATE KEY-----",
        "SSH private key",
    ),
    (
        "pkcs8-private-key",
        r"-----BEGIN PRIVATE KEY-----",
        "PKCS#8 private key",
    ),
    (
        "encrypted-private-key",
        r"-----BEGIN ENCRYPTED PRIVATE KEY-----",
        "Encrypted private key",
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
    def __init__(self, config: ScannerConfig | None = None):
        self._config = config or ScannerConfig()

    def scan(self, text: str) -> ScanResult:
        if not text:
            return ScanResult(contains_secret=False)

        matches: list[SecretMatch] = []
        for rule_id, pattern, description in _COMPILED_RULES:
            if pattern.search(text):
                matches.append(SecretMatch(rule_id=rule_id, description=description))

        entropy = self._config.entropy
        if entropy.enabled and contains_high_entropy_string(
            text,
            min_length=entropy.min_length,
            threshold=entropy.threshold,
        ):
            matches.append(
                SecretMatch(
                    rule_id="high-entropy",
                    description="High-entropy secret-like string",
                )
            )

        return ScanResult(contains_secret=bool(matches), matches=tuple(matches))


def scan_request_body(body: bytes, scanner_config: ScannerConfig | None = None) -> ScanResult:
    from app.audit.helpers import extract_prompt_text

    text = extract_prompt_text(body)
    if text is None and body:
        text = body.decode("utf-8", errors="replace")
    return SecretScanner(scanner_config).scan(text or "")
