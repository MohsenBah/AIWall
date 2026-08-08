# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Enforce dangerous-command policy from shell risk scores."""

from __future__ import annotations

from app.agents.extract import extract_agent_actions_from_body
from app.agents.risk import CommandRiskScore, score_shell_command
from app.agents.types import ACTION_SHELL
from app.config import AgentGuardrailsConfig
from app.policies.engine import PolicyResult


def max_shell_risk_from_body(body: bytes | None) -> CommandRiskScore | None:
    """Return the highest shell-command risk found in a request body."""
    actions = extract_agent_actions_from_body(body)
    scores = [
        score_shell_command(action.action_target)
        for action in actions
        if action.action_type == ACTION_SHELL
    ]
    if not scores:
        return None
    return max(scores, key=lambda item: item.score)


def evaluate_shell_guardrails(
    body: bytes | None,
    config: AgentGuardrailsConfig,
) -> PolicyResult | None:
    """Map the highest shell risk to block / warn / require_approval.

    Returns ``None`` when guardrails are disabled or no shell actions are present.
    Thresholds are inclusive (``score >= N``). ``require_approval`` is checked
    before ``block`` so the highest band wins.
    """
    if not config.enabled:
        return None

    best = max_shell_risk_from_body(body)
    if best is None:
        return None

    shell = config.shell
    rule_ids = best.matched_rules
    detail = f"shell risk {best.score} ({best.level})"

    if best.score >= shell.require_approval_above:
        return PolicyResult(
            action="require_approval",
            policy_id="agent-shell-require-approval",
            reason="dangerous-shell-command",
            rule_ids=rule_ids,
        )
    if best.score >= shell.block_above:
        return PolicyResult(
            action="block",
            policy_id="agent-shell-block",
            reason="dangerous-shell-command",
            rule_ids=rule_ids,
        )
    if best.score >= shell.warn_above:
        return PolicyResult(
            action="warn",
            policy_id="agent-shell-warn",
            reason=detail,
            rule_ids=rule_ids,
        )
    return None


def merge_policy_results(
    base: PolicyResult,
    extra: PolicyResult | None,
) -> PolicyResult:
    """Prefer the more severe policy action."""
    if extra is None:
        return base
    severity = {
        "allow": 0,
        "warn": 1,
        "redact": 2,
        "block": 3,
        "require_approval": 4,
    }
    base_rank = severity.get(base.action, 0)
    extra_rank = severity.get(extra.action, 0)
    if extra_rank > base_rank:
        return extra
    return base
