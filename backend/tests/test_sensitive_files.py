# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.guardrails import evaluate_file_guardrails
from app.agents.sensitive_files import match_sensitive_path
from app.config import AgentGuardrailsConfig, FileGuardrailConfig
from tests.conftest import write_test_config


@pytest.mark.parametrize(
    ("path", "rule_id"),
    [
        (".env", "dotenv-file"),
        ("/home/app/.env.production", "dotenv-file"),
        ("~/.aws/credentials", "aws-credentials"),
        ("/Users/me/.ssh/id_rsa", "ssh-private-key"),
        ("certs/server.pem", "private-key-file"),
        (".kube/config", "kubeconfig"),
        ("deploy/secrets.yaml", "secrets-store"),
        ("config/production.yaml", "prod-config"),
        ("config/app.production.json", "prod-config"),
        ("/etc/shadow", "etc-shadow"),
        (".npmrc", "netrc-npmrc"),
    ],
)
def test_match_sensitive_path_patterns(path: str, rule_id: str) -> None:
    hit = match_sensitive_path(path)
    assert hit is not None
    assert hit.rule_id == rule_id
    assert hit.reason


def test_non_sensitive_paths_are_clean() -> None:
    assert match_sensitive_path("src/main.py") is None
    assert match_sensitive_path("README.md") is None
    assert match_sensitive_path("docs/architecture.md") is None


def _file_body(path: str, tool_name: str = "read_file") -> bytes:
    return json.dumps(
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
                                "name": tool_name,
                                "arguments": json.dumps({"path": path}),
                            },
                        }
                    ],
                }
            ],
        }
    ).encode()


def test_evaluate_file_guardrails_flags_dotenv() -> None:
    config = AgentGuardrailsConfig(
        enabled=True,
        file=FileGuardrailConfig(action="block"),
    )
    result = evaluate_file_guardrails(_file_body(".env"), config)
    assert result is not None
    assert result.action == "block"
    assert result.policy_id == "agent-file-block"
    assert result.reason == "sensitive-file-access:dotenv-file"
    assert "dotenv-file" in result.rule_ids


def test_evaluate_file_guardrails_warn_action() -> None:
    config = AgentGuardrailsConfig(
        enabled=True,
        file=FileGuardrailConfig(action="warn"),
    )
    result = evaluate_file_guardrails(_file_body("/var/app/.aws/credentials"), config)
    assert result is not None
    assert result.action == "warn"
    assert result.policy_id == "agent-file-warn"
    assert "aws-credentials" in result.rule_ids


@pytest.mark.asyncio
async def test_proxy_blocks_sensitive_file_access(
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
  file:
    action: block
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
                                "id": "call_env",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path":"/app/.env"}',
                                },
                            }
                        ],
                    }
                ],
            },
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
                                "id": "call_src",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path":"src/app.py"}',
                                },
                            }
                        ],
                    }
                ],
            },
        )

    assert blocked.status_code == 403
    payload = blocked.json()["error"]
    assert payload["code"] == "policy_blocked"
    assert payload["policy"] == "agent-file-block"
    assert payload["reason"] == "sensitive-file-access:dotenv-file"
    assert "dotenv-file" in payload["rule_ids"]

    assert allowed.status_code == 200
    await http_client.aclose()
