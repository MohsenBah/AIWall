# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.guardrails import evaluate_shell_guardrails, merge_policy_results
from app.config import AgentGuardrailsConfig, ShellGuardrailConfig
from app.policies.engine import PolicyResult
from tests.conftest import write_test_config


def _shell_body(command: str) -> bytes:
    return json.dumps(
        {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "bash",
                                "arguments": json.dumps({"command": command}),
                            },
                        }
                    ],
                }
            ],
        }
    ).encode()


def test_evaluate_shell_guardrails_maps_risk_bands() -> None:
    config = AgentGuardrailsConfig(
        enabled=True,
        shell=ShellGuardrailConfig(
            warn_above=40,
            block_above=70,
            require_approval_above=90,
        ),
    )

    blocked = evaluate_shell_guardrails(_shell_body("rm -rf /tmp/workdir"), config)
    assert blocked is not None
    assert blocked.action == "block"
    assert blocked.policy_id == "agent-shell-block"
    assert blocked.reason == "dangerous-shell-command"

    approval = evaluate_shell_guardrails(_shell_body("rm -rf /"), config)
    assert approval is not None
    assert approval.action == "require_approval"
    assert approval.policy_id == "agent-shell-require-approval"

    warned = evaluate_shell_guardrails(_shell_body("sudo true"), config)
    assert warned is not None
    assert warned.action == "warn"

    allowed = evaluate_shell_guardrails(_shell_body("ls"), config)
    assert allowed is None


def test_guardrails_disabled_are_noop() -> None:
    config = AgentGuardrailsConfig(enabled=False)
    assert evaluate_shell_guardrails(_shell_body("rm -rf /"), config) is None


def test_merge_policy_results_prefers_require_approval() -> None:
    base = PolicyResult(action="warn", policy_id="warn-large-cost", reason="cost")
    extra = PolicyResult(
        action="require_approval",
        policy_id="agent-shell-require-approval",
        reason="dangerous-shell-command",
    )
    merged = merge_policy_results(base, extra)
    assert merged.action == "require_approval"
    assert merged.policy_id == "agent-shell-require-approval"


@pytest.mark.asyncio
async def test_proxy_blocks_high_risk_shell_when_configured(
    tmp_path,
    monkeypatch,
    upstream_mock_handler,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    config_path = write_test_config(
        tmp_path,
        policies_block="",
        extra_yaml="""
agent_guardrails:
  enabled: true
  approval_timeout_seconds: 1
  shell:
    warn_above: 40
    block_above: 70
    require_approval_above: 90
""".strip(),
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream_mock_handler))
    app = create_app(config_path=config_path, http_client=http_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        blocked = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_rm",
                                "type": "function",
                                "function": {
                                    "name": "bash",
                                    "arguments": '{"command":"rm -rf /tmp/cache"}',
                                },
                            }
                        ],
                    }
                ],
            },
        )
        approval = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_root",
                                "type": "function",
                                "function": {
                                    "name": "bash",
                                    "arguments": '{"command":"rm -rf /"}',
                                },
                            }
                        ],
                    }
                ],
            },
            timeout=5.0,
        )
        allowed = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_ls",
                                "type": "function",
                                "function": {
                                    "name": "bash",
                                    "arguments": '{"command":"ls"}',
                                },
                            }
                        ],
                    }
                ],
            },
        )

    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "policy_blocked"
    assert blocked.json()["error"]["policy"] == "agent-shell-block"
    assert blocked.headers.get("x-aiwall-policy-action") == "block"

    assert approval.status_code == 403
    assert approval.json()["error"]["code"] == "approval_required"
    assert approval.json()["error"]["reason"] == "approval-timeout"
    assert approval.json()["error"]["policy"] == "agent-shell-require-approval"
    assert approval.headers.get("x-aiwall-policy-action") == "require_approval"
    assert "approval_id" in approval.json()["error"]

    assert allowed.status_code == 200
    await http_client.aclose()
