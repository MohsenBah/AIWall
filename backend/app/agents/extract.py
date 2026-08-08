# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Extract agent actions from OpenAI-compatible request bodies.

Phase 5.1 stores tool calls with ``action_type`` + ``action_target``.
Richer classification (shell / file) lands in Phase 5.2+.
"""

from __future__ import annotations

import json
from typing import Any

from app.agents.types import (
    ACTION_TOOL_CALL,
    ARGUMENTS_PREVIEW_MAX,
    AgentAction,
)


def _preview_arguments(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        text = json.dumps(raw, separators=(",", ":"), ensure_ascii=False)
    else:
        text = str(raw)
    text = text.strip()
    if not text:
        return None
    if len(text) > ARGUMENTS_PREVIEW_MAX:
        return text[: ARGUMENTS_PREVIEW_MAX - 3] + "..."
    return text


def _action_from_function(
    *,
    name: Any,
    arguments: Any = None,
    tool_call_id: Any = None,
) -> AgentAction | None:
    if not isinstance(name, str):
        return None
    tool_name = name.strip()
    if not tool_name:
        return None
    call_id = tool_call_id.strip() if isinstance(tool_call_id, str) else None
    return AgentAction(
        action_type=ACTION_TOOL_CALL,
        action_target=tool_name,
        tool_name=tool_name,
        arguments_preview=_preview_arguments(arguments),
        tool_call_id=call_id or None,
    )


def _actions_from_tool_calls(tool_calls: Any) -> list[AgentAction]:
    if not isinstance(tool_calls, list):
        return []
    actions: list[AgentAction] = []
    for item in tool_calls:
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        if isinstance(function, dict):
            action = _action_from_function(
                name=function.get("name"),
                arguments=function.get("arguments"),
                tool_call_id=item.get("id"),
            )
        else:
            # Some clients flatten name onto the tool_call object.
            action = _action_from_function(
                name=item.get("name"),
                arguments=item.get("arguments"),
                tool_call_id=item.get("id"),
            )
        if action is not None:
            actions.append(action)
    return actions


def extract_agent_actions_from_body(body: bytes | None) -> tuple[AgentAction, ...]:
    """Return agent actions found in a chat-completions request body."""
    if not body:
        return ()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return ()
    if not isinstance(payload, dict):
        return ()

    actions: list[AgentAction] = []
    messages = payload.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            actions.extend(_actions_from_tool_calls(message.get("tool_calls")))
            function_call = message.get("function_call")
            if isinstance(function_call, dict):
                action = _action_from_function(
                    name=function_call.get("name"),
                    arguments=function_call.get("arguments"),
                )
                if action is not None:
                    actions.append(action)

    # Deduplicate identical tool_call_id + target pairs while preserving order.
    seen: set[tuple[str | None, str, str]] = set()
    unique: list[AgentAction] = []
    for action in actions:
        key = (action.tool_call_id, action.action_type, action.action_target)
        if key in seen:
            continue
        seen.add(key)
        unique.append(action)
    return tuple(unique)
