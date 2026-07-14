# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Regex-based secret detection for prompts and request bodies."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import RuleScannerConfig, ScannerConfig
from app.scanners.allowlist import AllowlistChecker
from app.scanners.entropy import contains_high_entropy_string


@dataclass(frozen=True)
class SecretMatch:
    rule_id: str
    description: str


@dataclass(frozen=True)
class ScanResult:
    contains_secret: bool
    matches: tuple[SecretMatch, ...] = ()


@dataclass(frozen=True)
class _SecretRule:
    rule_id: str
    pattern: re.Pattern[str]
    description: str
    default_min_length: int | None = None


_SECRET_RULES = (
    _SecretRule("aws-access-key", re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), "AWS access key ID"),
    _SecretRule(
        "github-token",
        re.compile(r"\b((?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,})\b"),
        "GitHub token",
    ),
    _SecretRule(
        "github-fine-grained-token",
        re.compile(r"\b(github_pat_[A-Za-z0-9_]{20,})\b"),
        "GitHub fine-grained token",
    ),
    _SecretRule(
        "slack-token",
        re.compile(r"\b(xox[abprsb]-[0-9A-Za-z-]{10,})\b"),
        "Slack token",
    ),
    _SecretRule(
        "stripe-secret-key",
        re.compile(r"\b(sk_(?:live|test)_[0-9a-zA-Z]{16,})\b"),
        "Stripe secret key",
    ),
    _SecretRule(
        "stripe-restricted-key",
        re.compile(r"\b(rk_(?:live|test)_[0-9a-zA-Z]{16,})\b"),
        "Stripe restricted key",
    ),
    _SecretRule(
        "google-api-key",
        re.compile(r"\b(AIza[0-9A-Za-z\-_]{35})\b"),
        "Google API key",
    ),
    _SecretRule(
        "azure-storage-key",
        re.compile(r"(?i)((?:AccountKey|SharedAccessKey)=['\"]?[A-Za-z0-9+/=]{40,})"),
        "Azure storage access key",
    ),
    _SecretRule(
        "gcp-service-account",
        re.compile(r'"type"\s*:\s*"service_account"'),
        "GCP service account JSON",
    ),
    _SecretRule(
        "database-url",
        re.compile(
            r"(?i)((?:postgres|postgresql|mysql|mongodb(?:\+srv)?|redis)"
            r"://[^\s:@/]+:[^\s@/]+@)"
        ),
        "Database connection URL with credentials",
    ),
    _SecretRule(
        "ssh-private-key",
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )PRIVATE KEY-----"),
        "SSH private key",
    ),
    _SecretRule(
        "pkcs8-private-key",
        re.compile(r"-----BEGIN PRIVATE KEY-----"),
        "PKCS#8 private key",
    ),
    _SecretRule(
        "encrypted-private-key",
        re.compile(r"-----BEGIN ENCRYPTED PRIVATE KEY-----"),
        "Encrypted private key",
    ),
    _SecretRule(
        "jwt",
        re.compile(
            r"\b(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b"
        ),
        "JSON Web Token",
    ),
    _SecretRule(
        "generic-api-key",
        re.compile(
            r"(?i)(?:api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*"
            r"['\"]?([A-Za-z0-9_\-]{8,})"
        ),
        "Generic API key assignment",
        16,
    ),
    _SecretRule(
        "dotenv-secret",
        re.compile(r"(?m)^([A-Z][A-Z0-9_]{2,}=(?:['\"]?)[^\s'\"]{8,})"),
        "Environment variable secret",
        12,
    ),
)


class SecretScanner:
    def __init__(self, config: ScannerConfig | None = None):
        self._config = config or ScannerConfig()
        self._allowlist = AllowlistChecker(
            ignore_examples=self._config.ignore_examples,
            allowlist=self._config.allowlist,
        )

    def _rule_config(self, rule_id: str) -> RuleScannerConfig:
        return self._config.rules.get(rule_id, RuleScannerConfig())

    def _rule_enabled(self, rule_id: str) -> bool:
        return self._rule_config(rule_id).enabled

    def _effective_min_length(self, rule: _SecretRule) -> int | None:
        override = self._rule_config(rule.rule_id).min_length
        if override is not None:
            return override
        return rule.default_min_length

    def _match_value(self, match: re.Match[str]) -> str:
        if match.lastindex:
            return match.group(1)
        return match.group(0)

    def _is_valid_match(self, rule: _SecretRule, matched: str) -> bool:
        min_length = self._effective_min_length(rule)
        if min_length is not None and len(matched) < min_length:
            return False
        return not self._allowlist.is_allowed(matched)

    def scan(self, text: str) -> ScanResult:
        if not text:
            return ScanResult(contains_secret=False)

        matches: list[SecretMatch] = []
        for rule in _SECRET_RULES:
            if not self._rule_enabled(rule.rule_id):
                continue
            for match in rule.pattern.finditer(text):
                matched = self._match_value(match)
                if not self._is_valid_match(rule, matched):
                    continue
                matches.append(SecretMatch(rule_id=rule.rule_id, description=rule.description))
                break

        entropy = self._config.entropy
        if entropy.enabled and self._rule_enabled("high-entropy"):
            if contains_high_entropy_string(
                text,
                min_length=entropy.min_length,
                threshold=entropy.threshold,
                is_allowed=self._allowlist.is_allowed,
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
