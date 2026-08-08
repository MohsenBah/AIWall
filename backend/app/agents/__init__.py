# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""AI agent guardrails (Phase 5): action model and extraction."""

from app.agents.approval_broker import ApprovalBroker
from app.agents.approval_models import (
    APPROVAL_APPROVED,
    APPROVAL_DENIED,
    APPROVAL_PENDING,
    APPROVAL_TIMED_OUT,
    PendingApprovalRow,
)
from app.agents.approval_store import ApprovalError, ApprovalStore, PendingApproval
from app.agents.approval_summary import summarize_agent_actions
from app.agents.classify import classify_function_call, parse_tool_arguments
from app.agents.extract import extract_agent_actions_from_body
from app.agents.guardrails import (
    evaluate_agent_guardrails,
    evaluate_file_guardrails,
    evaluate_shell_guardrails,
    find_sensitive_file_matches,
    max_shell_risk_from_body,
    merge_policy_results,
)
from app.agents.models import AgentActionRow
from app.agents.risk import (
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    CommandRiskScore,
    score_shell_command,
)
from app.agents.sensitive_files import match_sensitive_path
from app.agents.types import (
    ACTION_FILE_ACCESS,
    ACTION_SHELL,
    ACTION_TOOL_CALL,
    KNOWN_ACTION_TYPES,
    AgentAction,
)

__all__ = [
    "ACTION_FILE_ACCESS",
    "ACTION_SHELL",
    "ACTION_TOOL_CALL",
    "APPROVAL_APPROVED",
    "APPROVAL_DENIED",
    "APPROVAL_PENDING",
    "APPROVAL_TIMED_OUT",
    "AgentAction",
    "AgentActionRow",
    "ApprovalBroker",
    "ApprovalError",
    "ApprovalStore",
    "CommandRiskScore",
    "KNOWN_ACTION_TYPES",
    "PendingApproval",
    "PendingApprovalRow",
    "RISK_CRITICAL",
    "RISK_HIGH",
    "RISK_LOW",
    "RISK_MEDIUM",
    "classify_function_call",
    "evaluate_agent_guardrails",
    "evaluate_file_guardrails",
    "evaluate_shell_guardrails",
    "extract_agent_actions_from_body",
    "find_sensitive_file_matches",
    "match_sensitive_path",
    "max_shell_risk_from_body",
    "merge_policy_results",
    "parse_tool_arguments",
    "score_shell_command",
    "summarize_agent_actions",
]
