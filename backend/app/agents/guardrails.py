# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Enforce agent shell and sensitive-file guardrail policies."""

from __future__ import annotations

from app.agents.extract import extract_agent_actions_from_body
from app.agents.risk import CommandRiskScore, score_shell_command
from app.agents.sensitive_files import SensitivePathMatch, match_sensitive_path
from app.agents.types import ACTION_FILE_ACCESS, ACTION_SHELL
from app.config import AgentGuardrailsConfig
from app.policies.engine import PolicyResult

_FILE_ACTIONS = frozenset({"block", "warn", "require_approval"})


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


def find_sensitive_file_matches(body: bytes | None) -> tuple[SensitivePathMatch, ...]:
    """Return sensitive file-access matches from file agent actions."""
    actions = extract_agent_actions_from_body(body)
    matches: list[SensitivePathMatch] = []
    seen: set[str] = set()
    for action in actions:
        if action.action_type != ACTION_FILE_ACCESS:
            continue
        hit = match_sensitive_path(action.action_target)
        if hit is None or hit.path in seen:
            continue
        seen.add(hit.path)
        matches.append(hit)
    return tuple(matches)


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


def evaluate_file_guardrails(
    body: bytes | None,
    config: AgentGuardrailsConfig,
) -> PolicyResult | None:
    """Flag sensitive file paths referenced by file-access tool calls."""
    if not config.enabled:
        return None

    matches = find_sensitive_file_matches(body)
    if not matches:
        return None

    action = (config.file.action or "block").strip().lower()
    if action not in _FILE_ACTIONS:
        action = "block"

    first = matches[0]
    rule_ids = tuple(match.rule_id for match in matches)
    if action == "require_approval":
        policy_id = "agent-file-require-approval"
    elif action == "warn":
        policy_id = "agent-file-warn"
    else:
        policy_id = "agent-file-block"

    return PolicyResult(
        action=action,
        policy_id=policy_id,
        reason=f"sensitive-file-access:{first.rule_id}",
        rule_ids=rule_ids,
    )


def evaluate_agent_guardrails(
    body: bytes | None,
    config: AgentGuardrailsConfig,
) -> PolicyResult | None:
    """Evaluate shell and file guardrails; return the most severe result."""
    if not config.enabled:
        return None
    shell_result = evaluate_shell_guardrails(body, config)
    file_result = evaluate_file_guardrails(body, config)
    if shell_result is None and file_result is None:
        return None
    if shell_result is None:
        return file_result
    return merge_policy_results(shell_result, file_result)


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
