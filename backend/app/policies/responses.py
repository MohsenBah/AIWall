"""Structured error responses for blocked requests."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from app.policies.engine import PolicyResult


def policy_blocked_response(result: PolicyResult) -> JSONResponse:
    policy_name = result.policy_id or "unknown"
    return JSONResponse(
        status_code=403,
        content={
            "error": {
                "message": f"Request blocked by AIWall policy: {policy_name}",
                "type": "policy_blocked",
                "code": "policy_blocked",
                "policy": policy_name,
                "reason": result.reason,
            }
        },
    )
