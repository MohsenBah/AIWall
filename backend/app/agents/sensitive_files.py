# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Detect sensitive file paths in agent file-access actions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath


@dataclass(frozen=True)
class SensitivePathMatch:
    path: str
    rule_id: str
    reason: str


@dataclass(frozen=True)
class _PathRule:
    rule_id: str
    pattern: re.Pattern[str]
    reason: str


def _rule(rule_id: str, pattern: str, reason: str) -> _PathRule:
    return _PathRule(
        rule_id=rule_id,
        pattern=re.compile(pattern, re.IGNORECASE),
        reason=reason,
    )


# Match against normalized path strings (forward slashes, lowercase for name checks).
SENSITIVE_PATH_RULES: tuple[_PathRule, ...] = (
    _rule(
        "dotenv-file",
        r"(^|/)(\.env|\.env\.[^/]+|[^/]+\.env)(/|$)",
        "Environment file that often contains secrets",
    ),
    _rule(
        "aws-credentials",
        r"(^|/)\.aws/(credentials|config)(/|$)",
        "AWS credentials or config file",
    ),
    _rule(
        "gcp-service-account",
        r"(^|/)([^/]*service[_-]?account[^/]*\.json|[^/]*-key\.json)(/|$)",
        "Likely cloud service-account / key JSON",
    ),
    _rule(
        "ssh-private-key",
        r"(^|/)\.ssh/(id_rsa|id_dsa|id_ecdsa|id_ed25519|.*_rsa|.*_ed25519)(/|$)",
        "SSH private key file",
    ),
    _rule(
        "private-key-file",
        r"(^|/)([^/]+\.(pem|p12|pfx)|[^/]*private[_-]?key[^/]*)(/|$)",
        "Private key or certificate material",
    ),
    _rule(
        "kubeconfig",
        r"(^|/)(\.kube/config|kubeconfig[^/]*)(/|$)",
        "Kubernetes kubeconfig",
    ),
    _rule(
        "docker-config",
        r"(^|/)\.docker/config\.json(/|$)",
        "Docker config with registry credentials",
    ),
    _rule(
        "secrets-store",
        r"(^|/)(secrets?\.(ya?ml|json|toml|env)|credentials?\.(ya?ml|json|toml|env)|.*secrets?\.ya?ml)(/|$)",
        "Credentials or secrets store file",
    ),
    _rule(
        "prod-config",
        r"(^|/)([^/]*prod(uction)?[^/]*\.(env|ya?ml|json|toml|ini|conf)|[^/]*\.(prod|production)\.(env|ya?ml|json))(/|$)",
        "Production configuration file",
    ),
    _rule(
        "etc-shadow",
        r"(^|/)(etc/shadow|etc/gshadow|etc/master\.passwd)(/|$)",
        "System password hash file",
    ),
    _rule(
        "netrc-npmrc",
        r"(^|/)(\.netrc|\.npmrc|\.pypirc)(/|$)",
        "Tool auth config that often stores tokens",
    ),
    _rule(
        "git-credentials",
        r"(^|/)\.git-credentials(/|$)",
        "Git stored credentials",
    ),
)


def normalize_path(path: str) -> str:
    """Normalize a path for pattern matching (POSIX-ish, no trailing slash)."""
    text = path.strip().strip("\"'")
    if not text:
        return ""
    # file:// URIs
    if text.lower().startswith("file:"):
        text = re.sub(r"^file://", "", text, flags=re.IGNORECASE)
    text = text.replace("\\", "/")
    # Collapse duplicate slashes except leading // for UNC-ish paths.
    text = re.sub(r"/{2,}", "/", text)
    if len(text) > 1 and text.endswith("/"):
        text = text.rstrip("/")
    return text


def _basename(path: str) -> str:
    posix = PurePosixPath(path)
    name = posix.name
    if not name and path:
        name = PureWindowsPath(path.replace("/", "\\")).name
    return name


def match_sensitive_path(path: str | None) -> SensitivePathMatch | None:
    """Return the first sensitive-path rule that matches ``path``."""
    if not path or not str(path).strip():
        return None
    normalized = normalize_path(str(path))
    if not normalized:
        return None

    # Also test basename-only forms so ".env" and "/home/x/.env" both hit.
    candidates = [normalized]
    base = _basename(normalized)
    if base and base != normalized:
        candidates.append(base)
        candidates.append(f"/{base}")

    for candidate in candidates:
        for rule in SENSITIVE_PATH_RULES:
            if rule.pattern.search(candidate):
                return SensitivePathMatch(
                    path=normalized,
                    rule_id=rule.rule_id,
                    reason=rule.reason,
                )
    return None


def find_sensitive_paths(paths: list[str] | tuple[str, ...]) -> tuple[SensitivePathMatch, ...]:
    """Match a list of paths; preserves first-match order and dedupes by path."""
    seen: set[str] = set()
    matches: list[SensitivePathMatch] = []
    for path in paths:
        hit = match_sensitive_path(path)
        if hit is None or hit.path in seen:
            continue
        seen.add(hit.path)
        matches.append(hit)
    return tuple(matches)
