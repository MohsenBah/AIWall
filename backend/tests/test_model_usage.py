# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text

from app.audit.writer import AuditEvent, AuditWriter
from app.storage.database import init_db

pytest.importorskip("jinja2")


def _writer(tmp_path: Path, name: str = "usage.db") -> tuple[AuditWriter, str]:
    db_path = tmp_path / name
    url = f"sqlite:///{db_path.as_posix()}"
    engine = create_engine(url)
    init_db(engine)
    return AuditWriter(engine), url


def _event(
    *,
    request_id: str,
    provider: str,
    model: str,
    tokens: int,
    cost: float,
    latency_ms: float,
    timestamp: datetime,
) -> AuditEvent:
    return AuditEvent(
        request_id=request_id,
        provider=provider,
        model=model,
        decision="allow",
        reason="proxied",
        input_length=10,
        output_length=5,
        latency_ms=latency_ms,
        total_tokens=tokens,
        estimated_cost=cost,
        timestamp=timestamp,
    )


def test_model_usage_matches_sqlite_query(tmp_path: Path) -> None:
    writer, db_url = _writer(tmp_path)
    now = datetime(2026, 7, 26, 18, 0, tzinfo=UTC)

    writer.write(
        _event(
            request_id="1",
            provider="openai",
            model="gpt-4o-mini",
            tokens=100,
            cost=0.01,
            latency_ms=100.0,
            timestamp=now - timedelta(hours=1),
        )
    )
    writer.write(
        _event(
            request_id="2",
            provider="openai",
            model="gpt-4o-mini",
            tokens=50,
            cost=0.02,
            latency_ms=200.0,
            timestamp=now - timedelta(hours=2),
        )
    )
    writer.write(
        _event(
            request_id="3",
            provider="ollama",
            model="llama3.2",
            tokens=80,
            cost=0.0,
            latency_ms=40.0,
            timestamp=now - timedelta(hours=3),
        )
    )
    writer.write(
        _event(
            request_id="old",
            provider="openai",
            model="gpt-4o",
            tokens=999,
            cost=1.0,
            latency_ms=10.0,
            timestamp=now - timedelta(hours=48),
        )
    )

    report = writer.model_usage(window_hours=24, now=now)
    by_key = {(row.provider, row.model): row for row in report.rows}

    assert set(by_key) == {("openai", "gpt-4o-mini"), ("ollama", "llama3.2")}
    assert by_key[("openai", "gpt-4o-mini")].request_count == 2
    assert by_key[("openai", "gpt-4o-mini")].total_tokens == 150
    assert by_key[("openai", "gpt-4o-mini")].estimated_cost == pytest.approx(0.03)
    assert by_key[("openai", "gpt-4o-mini")].avg_latency_ms == pytest.approx(150.0)
    assert by_key[("ollama", "llama3.2")].request_count == 1
    assert by_key[("ollama", "llama3.2")].total_tokens == 80

    # Acceptance: aggregates match a direct SQLite query.
    engine = create_engine(db_url)
    since = now - timedelta(hours=24)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT provider, model,
                       COUNT(*) AS request_count,
                       COALESCE(SUM(total_tokens), 0) AS total_tokens,
                       COALESCE(SUM(estimated_cost), 0) AS estimated_cost,
                       COALESCE(AVG(latency_ms), 0) AS avg_latency_ms
                FROM audit_events
                WHERE timestamp >= :since
                GROUP BY provider, model
                """
            ),
            {"since": since},
        ).all()

    sql_by_key = {
        (provider, model): (
            int(request_count),
            int(total_tokens),
            float(estimated_cost),
            float(avg_latency_ms),
        )
        for provider, model, request_count, total_tokens, estimated_cost, avg_latency_ms in rows
    }
    for key, row in by_key.items():
        assert sql_by_key[key][0] == row.request_count
        assert sql_by_key[key][1] == row.total_tokens
        assert sql_by_key[key][2] == pytest.approx(row.estimated_cost)
        assert sql_by_key[key][3] == pytest.approx(row.avg_latency_ms)

    assert report.total_requests == 3
    assert report.total_tokens == 230
    assert report.total_estimated_cost == pytest.approx(0.03)


@pytest.mark.asyncio
async def test_usage_page_renders_model_rows(tmp_path: Path) -> None:
    import httpx

    from app.main import create_app
    from tests.conftest import write_test_config

    config_path = write_test_config(tmp_path, "")
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    )
    app = create_app(config_path=config_path, http_client=http_client)
    now = datetime.now(UTC)
    app.state.audit_writer.write(
        _event(
            request_id="p1",
            provider="openai",
            model="gpt-4o-mini",
            tokens=42,
            cost=0.001234,
            latency_ms=88.0,
            timestamp=now,
        )
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get("/usage")
        week = await client.get("/usage", params={"window_hours": 168})

    assert page.status_code == 200
    assert "Model usage" in page.text
    assert "gpt-4o-mini" in page.text
    assert "openai" in page.text
    assert "42" in page.text
    assert "0.001234" in page.text
    assert "88 ms" in page.text
    assert week.status_code == 200
    assert 'value="168"' in week.text
    await http_client.aclose()
