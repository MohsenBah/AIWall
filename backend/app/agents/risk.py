# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Command risk scoring for agent shell actions."""

from __future__ import annotations

import re
from dataclasses import dataclass

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"
RISK_CRITICAL = "critical"

KNOWN_RISK_LEVELS = frozenset({RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_CRITICAL})


@dataclass(frozen=True)
class RiskRuleMatch:
    rule_id: str
    score: int
    reason: str


@dataclass(frozen=True)
class CommandRiskScore:
    command: str
    score: int
    level: str
    matched_rules: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def is_high_risk(self) -> bool:
        return self.level in {RISK_HIGH, RISK_CRITICAL}


@dataclass(frozen=True)
class _PatternRule:
    rule_id: str
    pattern: re.Pattern[str]
    score: int
    reason: str


def _rule(rule_id: str, pattern: str, score: int, reason: str) -> _PatternRule:
    return _PatternRule(
        rule_id=rule_id,
        pattern=re.compile(pattern, re.IGNORECASE),
        score=score,
        reason=reason,
    )


_PATTERN_RULES: tuple[_PatternRule, ...] = (
    _rule("mkfs", r"\bmkfs(\.\w+)?\b", 100, "Filesystem format command"),
    _rule("dd-device", r"\bdd\b[^\n]*\bof=/dev/", 100, "Raw write to a block device"),
    _rule("wipefs", r"\bwipefs\b", 95, "Filesystem signature wipe"),
    _rule(
        "fork-bomb",
        r":\(\)\s*\{\s*:\|:&\s*\}\s*;\s*:",
        100,
        "Fork bomb pattern",
    ),
    _rule(
        "curl-pipe-shell",
        r"(curl|wget)\b[^\n|;]*\|\s*(ba)?sh\b",
        90,
        "Remote script piped into a shell",
    ),
    _rule(
        "shutdown-reboot",
        r"\b(shutdown|reboot|poweroff|halt)\b",
        80,
        "System power/state change",
    ),
    _rule(
        "kill-init",
        r"\bkill\s+(-9\s+)?1\b|\bkillall\s+(-9\s+)?init\b",
        85,
        "Signal to init/PID 1",
    ),
    _rule(
        "chmod-777-recursive",
        r"\bchmod\b[^\n]*\b-R\b[^\n]*\b777\b|\bchmod\b[^\n]*\b777\b[^\n]*\b-R\b",
        75,
        "Recursive world-writable permissions",
    ),
    _rule(
        "chown-recursive-root",
        r"\bchown\b[^\n]*\b-R\b[^\n]*/",
        70,
        "Recursive ownership change under /",
    ),
    _rule(
        "iptables-flush",
        r"\b(iptables|nft)\b[^\n]*\b(-F|--flush)\b",
        70,
        "Firewall rule flush",
    ),
    _rule("sudo", r"(^|[;&|]\s*)sudo\b", 55, "Elevated privileges via sudo"),
    _rule(
        "package-remove",
        r"\b(apt(-get)?|dnf|yum|pacman)\b[^\n]*\b(remove|purge|erase)\b",
        60,
        "Package removal",
    ),
)

_SAFE_READ_ONLY = re.compile(
    r"^\s*(ls|pwd|echo|whoami|which|whereis|date|uname|id|env|printenv|"
    r"cat|head|tail|wc|file|stat|find|grep|rg|less|more|tree|df|du|ps|"
    r"top|htop)\b",
    re.IGNORECASE,
)

_RM_BIN = re.compile(r"(^|[;&|]\s*)rm\b", re.IGNORECASE)
_HAS_RECURSIVE = re.compile(r"(^|\s)-[a-zA-Z]*r[a-zA-Z]*(\s|$)|--recursive\b", re.IGNORECASE)
_HAS_FORCE = re.compile(r"(^|\s)-[a-zA-Z]*f[a-zA-Z]*(\s|$)|--force\b", re.IGNORECASE)
_SENSITIVE_RM_TARGET = re.compile(
    r"(^|\s)(/|/\*|/~|/home\b|/Users\b|/etc\b|/var\b|/usr\b|/root\b)(\s|$)",
    re.IGNORECASE,
)

_DEFAULT_UNKNOWN_SCORE = 35


def level_for_score(score: int) -> str:
    if score >= 90:
        return RISK_CRITICAL
    if score >= 70:
        return RISK_HIGH
    if score >= 40:
        return RISK_MEDIUM
    return RISK_LOW


def _rm_rf_matches(command: str) -> list[RiskRuleMatch]:
    if not _RM_BIN.search(command):
        return []
    if not (_HAS_RECURSIVE.search(command) and _HAS_FORCE.search(command)):
        return []
    if _SENSITIVE_RM_TARGET.search(command):
        return [
            RiskRuleMatch(
                rule_id="rm-rf-root",
                score=100,
                reason="Recursive force delete targeting a sensitive root path",
            )
        ]
    return [
        RiskRuleMatch(
            rule_id="rm-rf",
            score=85,
            reason="Recursive force delete",
        )
    ]


def score_shell_command(command: str | None) -> CommandRiskScore:
    """Score a shell command for destructive / high-impact risk.

    Returns the maximum matching rule score. Safe read-only commands score low
    when no destructive rules match; unknown commands get a medium-low default.
    """
    text = (command or "").strip()
    if not text:
        return CommandRiskScore(
            command="",
            score=0,
            level=RISK_LOW,
            matched_rules=(),
            reasons=("Empty command",),
        )

    matches: list[RiskRuleMatch] = list(_rm_rf_matches(text))
    for rule in _PATTERN_RULES:
        if rule.pattern.search(text):
            matches.append(
                RiskRuleMatch(rule_id=rule.rule_id, score=rule.score, reason=rule.reason)
            )

    if matches:
        best = max(matches, key=lambda item: item.score)
        notable = sorted(
            (
                item
                for item in matches
                if item.score >= best.score - 15 or item.score >= 70
            ),
            key=lambda item: (-item.score, item.rule_id),
        )
        # Deduplicate by rule_id while preserving score order.
        seen: set[str] = set()
        unique: list[RiskRuleMatch] = []
        for item in notable:
            if item.rule_id in seen:
                continue
            seen.add(item.rule_id)
            unique.append(item)
        return CommandRiskScore(
            command=text,
            score=best.score,
            level=level_for_score(best.score),
            matched_rules=tuple(item.rule_id for item in unique),
            reasons=tuple(item.reason for item in unique),
        )

    if _SAFE_READ_ONLY.match(text):
        return CommandRiskScore(
            command=text,
            score=5,
            level=RISK_LOW,
            matched_rules=("safe-read-only",),
            reasons=("Common read-only / informational command",),
        )

    return CommandRiskScore(
        command=text,
        score=_DEFAULT_UNKNOWN_SCORE,
        level=level_for_score(_DEFAULT_UNKNOWN_SCORE),
        matched_rules=("unknown-command",),
        reasons=("Unrecognized command; default medium-low risk",),
    )
