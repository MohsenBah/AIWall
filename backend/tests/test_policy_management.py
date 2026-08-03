# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.policies.context import PolicyContext
from app.policies.engine import PolicyEngine
from app.policies.overrides import (
    load_policy_overrides,
    policy_overrides_path,
    set_policy_enabled,
)
from tests.conftest import write_test_config

pytest.importorskip("jinja2")


def test_set_policy_enabled_persists_and_hot_reloads(tmp_path: Path) -> None:
    config_path = write_test_config(
        tmp_path,
        """  - name: block-long-input
    when: input.length > 5
    action: block""",
    )
    engine = PolicyEngine(config_path)
    context = PolicyContext(body=b"hello world", model="gpt-4o-mini", input_length=11)

    assert engine.evaluate(context).action == "block"

    overrides_path = set_policy_enabled(config_path, "block-long-input", False)
    assert overrides_path.exists()
    assert load_policy_overrides(overrides_path)["block-long-input"] is False

    # Hot reload picks up the override without recreating the engine.
    assert engine.evaluate(context).action == "allow"

    # Survives a fresh engine / process-style reload.
    reloaded = PolicyEngine(config_path)
    assert reloaded.evaluate(context).action == "allow"
    config = load_config(config_path)
    by_name = {policy.name: policy for policy in config.policies}
    assert by_name["block-long-input"].enabled is False

    set_policy_enabled(config_path, "block-long-input", True)
    assert engine.evaluate(context).action == "block"


def test_policy_overrides_prefer_data_directory(tmp_path: Path) -> None:
    config_path = write_test_config(tmp_path, "")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = set_policy_enabled(config_path, "block-secrets", False)
    assert path == data_dir / "policy-overrides.yaml"
    assert path == policy_overrides_path(config_path)


@pytest.mark.asyncio
async def test_policies_page_toggle_disables_without_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    upstream_mock_handler,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    config_path = write_test_config(
        tmp_path,
        """  - name: block-long-input
    when: input.length > 5
    action: block""",
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream_mock_handler))
    app = create_app(config_path=config_path, http_client=http_client)

    long_body = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "hello world this is long"}],
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get("/policies")
        assert page.status_code == 200
        assert "block-long-input" in page.text
        assert "Policies" in page.text

        blocked = await client.post("/v1/chat/completions", json=long_body)
        assert blocked.status_code == 403

        toggle = await client.post(
            "/policies/block-long-input/enabled",
            params={"enabled": "false"},
            headers={"HX-Request": "true"},
        )
        assert toggle.status_code == 200
        assert "toggle-off" in toggle.text

        allowed = await client.post("/v1/chat/completions", json=long_body)
        assert allowed.status_code == 200

        # Override file survives and is re-read by a new app instance.
        app2 = create_app(config_path=config_path, http_client=http_client)
        transport2 = ASGITransport(app=app2)
        async with AsyncClient(transport=transport2, base_url="http://test") as client2:
            still_allowed = await client2.post("/v1/chat/completions", json=long_body)
        assert still_allowed.status_code == 200

    await http_client.aclose()
