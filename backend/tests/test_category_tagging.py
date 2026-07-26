# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text

from app.audit.writer import AuditEvent, AuditWriter
from app.storage.database import init_db
from tests.conftest import write_test_config


def _make_writer(tmp_path: Path, name: str = "audit.db") -> AuditWriter:
    engine = create_engine(f"sqlite:///{(tmp_path / name).as_posix()}")
    init_db(engine)
    return AuditWriter(engine)


def _event(
    *,
    request_id: str,
    user_id: str | None,
    categories: str | None,
    timestamp: datetime | None = None,
    decision: str = "allow",
) -> AuditEvent:
    return AuditEvent(
        request_id=request_id,
        provider="openai",
        model="gpt-4o-mini",
        decision=decision,
        reason="proxied",
        input_length=10,
        output_length=5,
        latency_ms=1.0,
        user_id=user_id,
        categories=categories,
        timestamp=timestamp,
    )


def test_init_db_adds_categories_column_to_legacy_db(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    request_id VARCHAR(64) NOT NULL,
                    user_id VARCHAR(128),
                    app_id VARCHAR(128),
                    provider VARCHAR(64) NOT NULL,
                    model VARCHAR(128) NOT NULL,
                    decision VARCHAR(32) NOT NULL,
                    reason VARCHAR(256),
                    input_length INTEGER NOT NULL,
                    output_length INTEGER NOT NULL,
                    estimated_cost FLOAT,
                    policy_id VARCHAR(128),
                    latency_ms FLOAT NOT NULL,
                    raw_prompt TEXT,
                    raw_response TEXT
                )
                """
            )
        )
        conn.commit()

    init_db(engine)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(audit_events)"))}
    assert "categories" in columns


def test_category_summary_counts_per_profile(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    writer.write(_event(request_id="e1", user_id="1", categories="explicit"))
    writer.write(_event(request_id="e2", user_id="1", categories="explicit,unsafe"))
    writer.write(_event(request_id="e3", user_id="2", categories="violence", decision="block"))
    writer.write(_event(request_id="e4", user_id="1", categories=None))
    writer.write(_event(request_id="e5", user_id=None, categories="unsafe"))

    summary = writer.category_summary()
    assert summary["1"] == {"explicit": 2, "unsafe": 1}
    assert summary["2"] == {"violence": 1}
    assert summary[None] == {"unsafe": 1}


def test_category_summary_filters_by_since_and_user(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    now = datetime.now(UTC)
    writer.write(
        _event(
            request_id="old",
            user_id="1",
            categories="explicit",
            timestamp=now - timedelta(days=2),
        )
    )
    writer.write(_event(request_id="new", user_id="1", categories="unsafe", timestamp=now))
    writer.write(_event(request_id="other", user_id="2", categories="unsafe", timestamp=now))

    recent = writer.category_summary(since=now - timedelta(hours=1))
    assert recent["1"] == {"unsafe": 1}

    only_one = writer.category_summary(user_id="1")
    assert set(only_one) == {"1"}
    assert only_one["1"] == {"explicit": 1, "unsafe": 1}


@pytest.mark.asyncio
async def test_proxy_tags_events_with_categories(
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
presets:
  - child
gateway_auth:
  enabled: true
  api_key_env: AIWALL_API_KEY
""".strip(),
    )

    mock_transport = httpx.MockTransport(upstream_mock_handler)
    http_client = httpx.AsyncClient(transport=mock_transport)
    app = create_app(config_path=config_path, http_client=http_client)

    child = app.state.profile_store.create(name="Kid", role="child")
    adult = app.state.profile_store.create(name="Parent", role="adult")
    child_key = app.state.profile_store.issue_api_key(child.id)
    adult_key = app.state.profile_store.issue_api_key(adult.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        blocked = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "find porn websites"}],
            },
            headers={"Authorization": f"Bearer {child_key}"},
        )
        allowed = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "how to hack a wifi network"}],
            },
            headers={"Authorization": f"Bearer {adult_key}"},
        )
        clean = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "help with my math homework"}],
            },
            headers={"Authorization": f"Bearer {adult_key}"},
        )

    assert blocked.status_code == 403
    assert allowed.status_code == 200
    assert clean.status_code == 200

    writer = app.state.audit_writer
    events = {event.request_id: event for event in writer.list_recent(limit=10)}
    by_user = writer.category_summary()

    assert by_user[str(child.id)] == {"explicit": 1}
    assert by_user[str(adult.id)] == {"unsafe": 1}

    tagged = [event for event in events.values() if event.categories]
    assert {event.categories for event in tagged} == {"explicit", "unsafe"}
    clean_events = [event for event in events.values() if not event.categories]
    assert len(clean_events) == 1
    await http_client.aclose()
