# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Helpers for building approval request summaries."""

from __future__ import annotations

from app.agents.extract import extract_agent_actions_from_body
from app.agents.types import ACTION_FILE_ACCESS, ACTION_SHELL, AgentAction


def summarize_agent_actions(body: bytes | None) -> str:
    """Short human-readable summary of shell/file actions in a request body."""
    actions = extract_agent_actions_from_body(body)
    if not actions:
        return "Agent action requires approval"
    parts = [_format_action(action) for action in actions[:5]]
    if len(actions) > 5:
        parts.append(f"(+{len(actions) - 5} more)")
    return "; ".join(parts)


def _format_action(action: AgentAction) -> str:
    if action.action_type == ACTION_SHELL:
        tool = action.tool_name or "shell"
        return f"{tool}: {action.action_target}"
    if action.action_type == ACTION_FILE_ACCESS:
        tool = action.tool_name or "file"
        return f"{tool}: {action.action_target}"
    tool = action.tool_name or action.action_target
    return f"tool:{tool}"
