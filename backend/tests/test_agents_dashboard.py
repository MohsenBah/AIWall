# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import asyncio

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.types import ACTION_FILE_ACCESS, ACTION_SHELL, AgentAction
from tests.conftest import write_test_config

pytest.importorskip("jinja2")


@pytest.fixture
async def agents_app(tmp_path, monkeypatch, upstream_mock_handler):
    from app.main import create_app

    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    config_path = write_test_config(
        tmp_path,
        policies_block="",
        extra_yaml="""
agent_guardrails:
  enabled: true
  approval_timeout_seconds: 30
  shell:
    warn_above: 40
    block_above: 70
    require_approval_above: 90
""".strip(),
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream_mock_handler))
    app = create_app(config_path=config_path, http_client=http_client)
    yield app
    await http_client.aclose()


@pytest.mark.asyncio
async def test_agents_page_lists_actions_and_approvals(agents_app) -> None:
    agents_app.state.audit_writer.write_agent_actions(
        request_id="req-gui-1",
        actions=(
            AgentAction(
                action_type=ACTION_SHELL,
                action_target="ls -la",
                tool_name="bash",
            ),
            AgentAction(
                action_type=ACTION_FILE_ACCESS,
                action_target="/home/user/.env",
                tool_name="read_file",
            ),
        ),
    )
    pending = agents_app.state.approval_store.create(
        request_id="req-pending",
        policy_id="agent-shell-require-approval",
        reason="dangerous-shell-command",
        rule_ids=(),
        summary="bash: rm -rf /",
        provider="openai",
        model="gpt-4o-mini",
    )

    transport = ASGITransport(app=agents_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get("/agents")
        assert page.status_code == 200
        assert "Pending approvals" in page.text
        assert "Agent action log" in page.text
        assert "ls -la" in page.text
        assert ".env" in page.text
        assert f"#{pending.id}" in page.text
        assert "rm -rf /" in page.text
        assert "Approve" in page.text
        assert "Deny" in page.text

        filtered = await client.get("/partials/agent-actions", params={"action_type": "shell"})
        assert filtered.status_code == 200
        assert "ls -la" in filtered.text
        assert ".env" not in filtered.text


@pytest.mark.asyncio
async def test_agents_gui_approve_releases_held_request(
    agents_app,
) -> None:
    transport = ASGITransport(app=agents_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        held = asyncio.create_task(
            client.post(
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
            )
        )
        approval_id: int | None = None
        for _ in range(50):
            partial = await client.get("/partials/approvals")
            assert partial.status_code == 200
            if "Approve" in partial.text and "#" in partial.text:
                listed = await client.get("/approvals")
                items = listed.json()["approvals"]
                if items:
                    approval_id = int(items[0]["id"])
                    break
            await asyncio.sleep(0.05)

        assert approval_id is not None
        decided = await client.post(
            f"/agents/approvals/{approval_id}/approve",
            headers={"HX-Request": "true"},
        )
        assert decided.status_code == 200
        assert "No pending approvals" in decided.text

        response = await asyncio.wait_for(held, timeout=5.0)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_agents_gui_deny_blocks_held_request(agents_app) -> None:
    transport = ASGITransport(app=agents_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        held = asyncio.create_task(
            client.post(
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
            )
        )
        approval_id: int | None = None
        for _ in range(50):
            listed = await client.get("/approvals")
            items = listed.json()["approvals"]
            if items:
                approval_id = int(items[0]["id"])
                break
            await asyncio.sleep(0.05)

        assert approval_id is not None
        denied = await client.post(
            f"/agents/approvals/{approval_id}/deny",
            headers={"HX-Request": "true"},
        )
        assert denied.status_code == 200
        assert "No pending approvals" in denied.text

        response = await asyncio.wait_for(held, timeout=5.0)
        assert response.status_code == 403
        assert response.json()["error"]["reason"] == "approval-denied"
