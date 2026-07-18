# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Policy evaluation engine with hot reload from aiwall.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import AIWallConfig, load_config
from app.policies.conditions import evaluate_condition
from app.policies.context import PolicyContext


@dataclass(frozen=True)
class PolicyResult:
    action: str
    policy_id: str | None = None
    reason: str | None = None
    rule_ids: tuple[str, ...] = ()


def _match_reason(when: str) -> str:
    expression = when.strip()
    if expression == "input.contains_secret":
        return "secret-detected"
    if expression == "input.contains_private_key":
        return "private-key-detected"
    return when


class PolicyEngine:
    def __init__(self, config_path: Path):
        self._config_path = config_path
        self._cached_mtime: float | None = None
        self._cached_config: AIWallConfig | None = None

    def reload(self) -> AIWallConfig:
        if not self._config_path.exists():
            self._cached_mtime = None
            self._cached_config = AIWallConfig()
            return self._cached_config

        mtime = self._config_path.stat().st_mtime
        if self._cached_config is not None and self._cached_mtime == mtime:
            return self._cached_config

        config = load_config(self._config_path)
        self._cached_mtime = mtime
        self._cached_config = config
        return config

    def evaluate(self, context: PolicyContext) -> PolicyResult:
        config = self.reload()
        block_match: PolicyResult | None = None
        redact_match: PolicyResult | None = None
        warn_match: PolicyResult | None = None

        for policy in config.policies:
            if not policy.enabled:
                continue
            try:
                matched = evaluate_condition(policy.when, context)
            except ValueError:
                continue

            if not matched:
                continue

            if policy.action == "block":
                block_match = PolicyResult(
                    action="block",
                    policy_id=policy.name,
                    reason=_match_reason(policy.when),
                )
                break
            if policy.action == "redact" and redact_match is None:
                redact_match = PolicyResult(
                    action="redact",
                    policy_id=policy.name,
                    reason=_match_reason(policy.when),
                )
            if policy.action == "warn" and warn_match is None:
                warn_match = PolicyResult(
                    action="warn",
                    policy_id=policy.name,
                    reason=_match_reason(policy.when),
                )

        if block_match is not None:
            return block_match
        if redact_match is not None:
            return redact_match
        if warn_match is not None:
            return warn_match
        return PolicyResult(action="allow", reason="policy_allow")
