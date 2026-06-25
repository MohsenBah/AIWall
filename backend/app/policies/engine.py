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


class PolicyEngine:
    def __init__(self, config_path: Path):
        self._config_path = config_path

    def reload(self) -> AIWallConfig:
        return load_config(self._config_path)

    def evaluate(self, context: PolicyContext) -> PolicyResult:
        config = self.reload()
        block_match: PolicyResult | None = None
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
                    reason=policy.when,
                )
                break
            if policy.action == "warn" and warn_match is None:
                warn_match = PolicyResult(
                    action="warn",
                    policy_id=policy.name,
                    reason=policy.when,
                )

        if block_match is not None:
            return block_match
        if warn_match is not None:
            return warn_match
        return PolicyResult(action="allow", reason="policy_allow")
