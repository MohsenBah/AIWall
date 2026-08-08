# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Agent action types for Phase 5 guardrails."""

from __future__ import annotations

from dataclasses import dataclass

ACTION_TOOL_CALL = "tool_call"
ACTION_SHELL = "shell"
ACTION_FILE_ACCESS = "file_access"

KNOWN_ACTION_TYPES = frozenset(
    {
        ACTION_TOOL_CALL,
        ACTION_SHELL,
        ACTION_FILE_ACCESS,
    }
)

ARGUMENTS_PREVIEW_MAX = 500


@dataclass(frozen=True)
class AgentAction:
    """One observed agent/tool action attached to a proxied request."""

    action_type: str
    action_target: str
    tool_name: str | None = None
    arguments_preview: str | None = None
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        if self.action_type not in KNOWN_ACTION_TYPES:
            raise ValueError(f"Unknown action_type: {self.action_type}")
        if not self.action_target.strip():
            raise ValueError("action_target is required")
