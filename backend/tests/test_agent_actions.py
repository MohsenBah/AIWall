# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import json
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text

from app.agents import (
    ACTION_FILE_ACCESS,
    ACTION_SHELL,
    ACTION_TOOL_CALL,
    AgentAction,
    classify_function_call,
    extract_agent_actions_from_body,
)
from app.audit.writer import AuditWriter
from app.storage.database import init_db
from tests.conftest import write_test_config


def test_classify_shell_and_file_tool_names() -> None:
    assert classify_function_call(
        name="bash",
        arguments='{"command":"rm -rf /tmp/x"}',
    ) == (ACTION_SHELL, "rm -rf /tmp/x")

    assert classify_function_call(
        name="read_file",
        arguments='{"path":"/etc/passwd"}',
    ) == (ACTION_FILE_ACCESS, "/etc/passwd")

    assert classify_function_call(
        name="get_weather",
        arguments='{"city":"Toronto"}',
    ) == (ACTION_TOOL_CALL, "get_weather")


def test_classify_by_argument_shape_for_unknown_tools() -> None:
    assert classify_function_call(
        name="custom_runner",
        arguments={"command": "ls"},
    ) == (ACTION_SHELL, "ls")

    assert classify_function_call(
        name="custom_reader",
        arguments={"target_file": "src/main.py"},
    ) == (ACTION_FILE_ACCESS, "src/main.py")


def test_extract_classifies_shell_tool_call() -> None:
    body = json.dumps(
        {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "user", "content": "list files"},
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "run_terminal",
                                "arguments": '{"command":"ls -la"}',
                            },
                        }
                    ],
                },
            ],
        }
    ).encode()

    actions = extract_agent_actions_from_body(body)
    assert len(actions) == 1
    assert actions[0].action_type == ACTION_SHELL
    assert actions[0].action_target == "ls -la"
    assert actions[0].tool_name == "run_terminal"
    assert actions[0].tool_call_id == "call_1"
    assert actions[0].arguments_preview is not None
    assert "ls -la" in actions[0].arguments_preview


def test_extract_classifies_file_and_generic_calls() -> None:
    body = json.dumps(
        {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_file",
                            "type": "function",
                            "function": {
                                "name": "Write",
                                "arguments": json.dumps({"path": ".env", "contents": "X=1"}),
                            },
                        },
                        {
                            "id": "call_tool",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"city":"Toronto"}',
                            },
                        },
                    ],
                },
                {
                    "role": "assistant",
                    "function_call": {
                        "name": "Shell",
                        "arguments": '{"command":"pwd"}',
                    },
                },
            ],
        }
    ).encode()

    actions = extract_agent_actions_from_body(body)
    by_id = {action.tool_call_id: action for action in actions if action.tool_call_id}
    assert by_id["call_file"].action_type == ACTION_FILE_ACCESS
    assert by_id["call_file"].action_target == ".env"
    assert by_id["call_tool"].action_type == ACTION_TOOL_CALL
    assert by_id["call_tool"].action_target == "get_weather"

    legacy = [action for action in actions if action.tool_call_id is None]
    assert len(legacy) == 1
    assert legacy[0].action_type == ACTION_SHELL
    assert legacy[0].action_target == "pwd"


def test_write_agent_action_persists_type_and_target(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'agent.db').as_posix()}")
    init_db(engine)
    writer = AuditWriter(engine)

    rows = writer.write_agent_actions(
        request_id="req-1",
        audit_event_id=42,
        actions=[
            AgentAction(
                action_type=ACTION_FILE_ACCESS,
                action_target=".env",
                tool_name="read_file",
                arguments_preview='{"path":".env"}',
            )
        ],
    )
    assert len(rows) == 1
    assert rows[0].action_type == ACTION_FILE_ACCESS
    assert rows[0].action_target == ".env"

    listed = writer.list_agent_actions(request_id="req-1")
    assert len(listed) == 1
    assert listed[0].action_type == ACTION_FILE_ACCESS
    assert listed[0].action_target == ".env"
    assert listed[0].audit_event_id == 42


def test_init_db_creates_agent_actions_table(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE audit_events (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT,
                    request_id TEXT,
                    provider TEXT,
                    model TEXT,
                    decision TEXT,
                    reason TEXT,
                    input_length INTEGER,
                    output_length INTEGER,
                    latency_ms REAL
                )
                """
            )
        )
        conn.commit()
    init_db(engine)
    with engine.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
    assert "agent_actions" in tables


@pytest.mark.asyncio
async def test_proxy_stores_classified_shell_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    upstream_mock_handler,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    config_path = write_test_config(tmp_path, "")
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream_mock_handler))
    app = create_app(config_path=config_path, http_client=http_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": "run a command"},
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_shell",
                                "type": "function",
                                "function": {
                                    "name": "bash",
                                    "arguments": '{"command":"echo hi"}',
                                },
                            }
                        ],
                    },
                ],
            },
        )

    assert response.status_code == 200
    actions = app.state.audit_writer.list_agent_actions(request_id=None, limit=10)
    assert len(actions) >= 1
    match = next(action for action in actions if action.tool_call_id == "call_shell")
    assert match.action_type == ACTION_SHELL
    assert match.action_target == "echo hi"
    assert match.tool_name == "bash"
    assert match.audit_event_id is not None
    await http_client.aclose()
