# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Structured error responses for blocked requests."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from app.policies.engine import PolicyResult

RULE_IDS_HEADER = "X-AIWall-Rule-Ids"
POLICY_ACTION_HEADER = "X-AIWall-Policy-Action"


def policy_blocked_response(result: PolicyResult) -> JSONResponse:
    policy_name = result.policy_id or "unknown"
    error: dict[str, object] = {
        "message": f"Request blocked by AIWall policy: {policy_name}",
        "type": "policy_blocked",
        "code": "policy_blocked",
        "policy": policy_name,
        "reason": result.reason,
    }
    if result.rule_ids:
        error["rule_ids"] = list(result.rule_ids)

    headers: dict[str, str] = {}
    if result.rule_ids:
        headers[RULE_IDS_HEADER] = ",".join(result.rule_ids)
    headers[POLICY_ACTION_HEADER] = "block"

    return JSONResponse(
        status_code=403,
        content={"error": error},
        headers=headers,
    )


def privacy_safe_headers(result: PolicyResult) -> dict[str, str]:
    """Headers that surface policy/rule metadata without secret values."""
    headers: dict[str, str] = {}
    if result.action in {"warn", "redact"}:
        headers[POLICY_ACTION_HEADER] = result.action
    if result.rule_ids:
        headers[RULE_IDS_HEADER] = ",".join(result.rule_ids)
    return headers
