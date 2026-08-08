# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine

from app.audit.writer import AuditEvent, AuditWriter
from app.config import load_config
from app.settings.overrides import (
    load_settings_overrides,
    settings_overrides_path,
    update_logging_settings,
)
from app.storage.database import init_db
from tests.conftest import write_test_config

pytest.importorskip("jinja2")


def test_update_logging_settings_persists_and_reloads(tmp_path: Path) -> None:
    config_path = write_test_config(tmp_path, "")
    assert load_config(config_path).logging.log_raw_prompts is False
    assert load_config(config_path).logging.retention_days == 90

    path = update_logging_settings(
        config_path,
        log_raw_prompts=True,
        retention_days=14,
    )
    assert path.exists()
    overrides = load_settings_overrides(path)
    assert overrides["logging"]["log_raw_prompts"] is True
    assert overrides["logging"]["retention_days"] == 14

    config = load_config(config_path)
    assert config.logging.log_raw_prompts is True
    assert config.logging.retention_days == 14


def test_settings_overrides_prefer_data_directory(tmp_path: Path) -> None:
    config_path = write_test_config(tmp_path, "")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = update_logging_settings(config_path, retention_days=7)
    assert path == data_dir / "settings-overrides.yaml"
    assert path == settings_overrides_path(config_path)


def test_purge_expired_events_respects_retention(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'purge.db').as_posix()}")
    init_db(engine)
    writer = AuditWriter(engine)
    now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    writer.write(
        AuditEvent(
            request_id="keep",
            provider="openai",
            model="gpt-4o-mini",
            decision="allow",
            reason="proxied",
            input_length=1,
            output_length=1,
            latency_ms=1.0,
            timestamp=now - timedelta(days=2),
        )
    )
    writer.write(
        AuditEvent(
            request_id="drop",
            provider="openai",
            model="gpt-4o-mini",
            decision="allow",
            reason="proxied",
            input_length=1,
            output_length=1,
            latency_ms=1.0,
            timestamp=now - timedelta(days=40),
        )
    )

    deleted = writer.purge_expired_events(30, now=now)
    assert deleted == 1
    remaining = writer.list_recent(limit=10)
    assert len(remaining) == 1
    assert remaining[0].request_id == "keep"


@pytest.mark.asyncio
async def test_settings_page_toggle_and_retention_take_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    upstream_mock_handler,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    config_path = write_test_config(tmp_path, "")
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream_mock_handler))
    app = create_app(config_path=config_path, http_client=http_client)

    # Seed an old event that retention should purge.
    app.state.audit_writer.write(
        AuditEvent(
            request_id="old",
            provider="openai",
            model="gpt-4o-mini",
            decision="allow",
            reason="proxied",
            input_length=1,
            output_length=1,
            latency_ms=1.0,
            timestamp=datetime.now(UTC) - timedelta(days=60),
        )
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get("/settings")
        assert page.status_code == 200
        assert "Settings" in page.text
        assert "openai" in page.text
        assert "Raw prompt logging" in page.text

        missing_prompts = await client.get("/prompts")
        assert missing_prompts.status_code == 404

        toggle = await client.post(
            "/settings/logging/raw-prompts",
            params={"enabled": "true"},
            headers={"HX-Request": "true"},
        )
        assert toggle.status_code == 200
        assert "toggle-on" in toggle.text
        assert app.state.config.logging.log_raw_prompts is True

        prompts = await client.get("/prompts")
        assert prompts.status_code == 200

        # New chat should store a raw prompt while enabled.
        chat = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "settings check"}],
            },
        )
        assert chat.status_code == 200
        rows = app.state.audit_writer.search_events(limit=5, has_raw_prompt=True)
        assert rows.total >= 1

        retention = await client.post(
            "/settings/logging/retention",
            params={"days": "7"},
            headers={"HX-Request": "true"},
        )
        assert retention.status_code == 200
        assert "Retention set to 7 days" in retention.text
        assert app.state.config.logging.retention_days == 7
        assert "purged 1 expired" in retention.text

        # Survives a fresh app instance.
        app2 = create_app(config_path=config_path, http_client=http_client)
        assert app2.state.config.logging.log_raw_prompts is True
        assert app2.state.config.logging.retention_days == 7

    await http_client.aclose()
