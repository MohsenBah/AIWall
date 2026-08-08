# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Classify tool/function calls as shell, file access, or generic tool_call."""

from __future__ import annotations

import json
import re
from typing import Any

from app.agents.types import (
    ACTION_FILE_ACCESS,
    ACTION_SHELL,
    ACTION_TOOL_CALL,
)

# Normalized tool-name tokens (lowercase, separators stripped for matching).
_SHELL_TOOL_NAMES = frozenset(
    {
        "bash",
        "shell",
        "zsh",
        "sh",
        "powershell",
        "pwsh",
        "cmd",
        "terminal",
        "run_terminal",
        "runterminal",
        "run_command",
        "runcommand",
        "run_shell",
        "runshell",
        "run_shell_command",
        "runshellcommand",
        "execute_command",
        "executecommand",
        "execute_shell",
        "local_shell",
        "localshell",
        "shell_command",
        "shellcommand",
    }
)

_FILE_TOOL_NAMES = frozenset(
    {
        "read_file",
        "readfile",
        "write_file",
        "writefile",
        "edit_file",
        "editfile",
        "delete_file",
        "deletefile",
        "create_file",
        "createfile",
        "open_file",
        "openfile",
        "view_file",
        "viewfile",
        "list_dir",
        "listdir",
        "list_directory",
        "listdirectory",
        "str_replace",
        "strreplace",
        "search_replace",
        "searchreplace",
        "apply_patch",
        "applypatch",
        "glob",
        "grep",
        "read",
        "write",
        "edit",
    }
)

_SHELL_ARG_KEYS = (
    "command",
    "cmd",
    "script",
    "shell_command",
    "code",
)

_FILE_ARG_KEYS = (
    "path",
    "file",
    "file_path",
    "filepath",
    "filename",
    "target_file",
    "target",
    "uri",
)


def normalize_tool_name(name: str) -> str:
    """Lowercase and strip non-alphanumeric separators for matching."""
    return re.sub(r"[^a-z0-9]+", "", name.strip().lower())


def parse_tool_arguments(raw: Any) -> dict[str, Any]:
    """Parse tool arguments from a dict or JSON/string payload."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"_raw": text}
        if isinstance(parsed, dict):
            return parsed
        return {"_raw": parsed}
    return {"_raw": raw}


def _first_string_arg(arguments: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def classify_function_call(
    *,
    name: str,
    arguments: Any = None,
) -> tuple[str, str]:
    """Return ``(action_type, action_target)`` for a function/tool call.

    Shell tools use the command string as the target when present.
    File tools use the path/file argument when present.
    Otherwise the target is the tool name and the type is ``tool_call``.
    """
    tool_name = name.strip()
    if not tool_name:
        raise ValueError("tool name is required")

    parsed = parse_tool_arguments(arguments)
    normalized = normalize_tool_name(tool_name)

    shell_command = _first_string_arg(parsed, _SHELL_ARG_KEYS)
    file_path = _first_string_arg(parsed, _FILE_ARG_KEYS)

    if normalized in _SHELL_TOOL_NAMES:
        return ACTION_SHELL, shell_command or tool_name
    if normalized in _FILE_TOOL_NAMES:
        return ACTION_FILE_ACCESS, file_path or tool_name
    # Unknown tool names: classify by argument shape when unambiguous.
    if shell_command is not None and file_path is None:
        return ACTION_SHELL, shell_command
    if file_path is not None and shell_command is None:
        return ACTION_FILE_ACCESS, file_path
    return ACTION_TOOL_CALL, tool_name
