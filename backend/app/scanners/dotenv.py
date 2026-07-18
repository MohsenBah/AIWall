# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Heuristics for pasted .env files and credential dumps."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Upper-snake KEY=value lines typical of dotenv files.
_DOTENV_LINE = re.compile(
    r"(?m)^(?:export\s+)?([A-Z][A-Z0-9_]{1,64})=("
    r"(?:'[^'\n]{4,}'|\"[^\"\n]{4,}\"|[^\s#'\"\n]{4,})"
    r")\s*$"
)

# Broader assignment lines for large pasted config/credential dumps.
_ASSIGNMENT_LINE = re.compile(
    r"(?m)^([A-Za-z_][A-Za-z0-9_.-]{1,64})\s*[:=]\s*"
    r"('[^'\n]{6,}'|\"[^\"\n]{6,}\"|[^\s#'\"\n]{6,})\s*$"
)

_CREDENTIAL_KEY = re.compile(
    r"(?i)(?:"
    r"PASSWORD|PASSWD|SECRET|TOKEN|API[_-]?KEY|PRIVATE[_-]?KEY|"
    r"ACCESS[_-]?KEY|AUTH(?:_?TOKEN)?|CREDENTIAL|DATABASE_URL|"
    r"DB_(?:PASS|PASSWORD|URL)|CONNECTION_STRING|CLIENT_SECRET|"
    r"AWS_SECRET|OPENAI_API_KEY|GITHUB_TOKEN"
    r")"
)

_COMMON_NON_SECRET_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "USERNAME",
        "LOGNAME",
        "SHELL",
        "TERM",
        "LANG",
        "LC_ALL",
        "PWD",
        "OLDPWD",
        "EDITOR",
        "VISUAL",
        "TMPDIR",
        "TEMP",
        "TMP",
        "HOSTNAME",
        "HOSTTYPE",
        "OSTYPE",
        "MACHTYPE",
        "SHLVL",
        "PYTHONPATH",
        "NODE_ENV",
        "NODE_OPTIONS",
        "JAVA_HOME",
        "GOPATH",
        "GOROOT",
        "CARGO_HOME",
        "RUSTUP_HOME",
        "DISPLAY",
        "COLORTERM",
        "TERM_PROGRAM",
        "SSH_CONNECTION",
        "SSH_CLIENT",
        "XDG_RUNTIME_DIR",
        "XDG_SESSION_TYPE",
        "DBUS_SESSION_BUS_ADDRESS",
    }
)


@dataclass(frozen=True)
class DotenvLine:
    start: int
    end: int
    key: str
    value: str


@dataclass(frozen=True)
class DotenvDetection:
    line_count: int
    lines: tuple[DotenvLine, ...] = ()

    @property
    def detected(self) -> bool:
        return self.line_count > 0


def _value_length(raw_value: str) -> int:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return len(value) - 2
    return len(value)


def find_dotenv_lines(text: str, *, min_value_length: int = 8) -> list[DotenvLine]:
    lines: list[DotenvLine] = []
    for match in _DOTENV_LINE.finditer(text):
        key = match.group(1)
        value = match.group(2)
        if key.upper() in _COMMON_NON_SECRET_KEYS:
            continue
        if _value_length(value) < min_value_length:
            continue
        lines.append(
            DotenvLine(
                start=match.start(),
                end=match.end(),
                key=key,
                value=value,
            )
        )
    return lines


def find_assignment_lines(text: str, *, min_value_length: int = 8) -> list[DotenvLine]:
    lines: list[DotenvLine] = []
    for match in _ASSIGNMENT_LINE.finditer(text):
        key = match.group(1)
        value = match.group(2)
        if key.upper() in _COMMON_NON_SECRET_KEYS:
            continue
        if _value_length(value) < min_value_length:
            continue
        lines.append(
            DotenvLine(
                start=match.start(),
                end=match.end(),
                key=key,
                value=value,
            )
        )
    return lines


def detect_dotenv_block(
    text: str,
    *,
    min_lines: int = 2,
    min_value_length: int = 8,
    pasted_file_min_lines: int = 5,
) -> DotenvDetection:
    """Detect pasted .env bodies and large credential/config dumps.

    Triggers when:
    - at least ``min_lines`` dotenv-style assignments are present, or
    - one or more credential-named dotenv keys are present, or
    - a large pasted assignment dump (``pasted_file_min_lines``+) includes
      at least one credential-looking key.
    """
    if not text:
        return DotenvDetection(line_count=0)

    dotenv_lines = find_dotenv_lines(text, min_value_length=min_value_length)
    credential_lines = [line for line in dotenv_lines if _CREDENTIAL_KEY.search(line.key)]

    if len(dotenv_lines) >= min_lines or credential_lines:
        return DotenvDetection(line_count=len(dotenv_lines), lines=tuple(dotenv_lines))

    assignment_lines = find_assignment_lines(text, min_value_length=min_value_length)
    credential_assignments = [
        line for line in assignment_lines if _CREDENTIAL_KEY.search(line.key)
    ]
    if len(assignment_lines) >= pasted_file_min_lines and credential_assignments:
        return DotenvDetection(
            line_count=len(assignment_lines),
            lines=tuple(assignment_lines),
        )

    return DotenvDetection(line_count=0)
