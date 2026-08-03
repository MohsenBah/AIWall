# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine

from app.audit.writer import AuditEvent, AuditWriter
from app.storage.database import init_db

pytest.importorskip("jinja2")


def _writer(tmp_path: Path) -> AuditWriter:
    engine = create_engine(f"sqlite:///{(tmp_path / 'trends.db').as_posix()}")
    init_db(engine)
    return AuditWriter(engine)


def _event(*, cost: float, timestamp: datetime, request_id: str) -> AuditEvent:
    return AuditEvent(
        request_id=request_id,
        provider="openai",
        model="gpt-4o-mini",
        decision="allow",
        reason="proxied",
        input_length=10,
        output_length=5,
        latency_ms=1.0,
        estimated_cost=cost,
        timestamp=timestamp,
    )


def test_usage_timeseries_matches_db_buckets(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    # Fixed "now" so bucket alignment is deterministic.
    now = datetime(2026, 7, 26, 15, 30, tzinfo=UTC)
    hour_a = datetime(2026, 7, 26, 13, 10, tzinfo=UTC)
    hour_b = datetime(2026, 7, 26, 14, 45, tzinfo=UTC)
    outside = datetime(2026, 7, 25, 10, 0, tzinfo=UTC)

    writer.write(_event(cost=0.01, timestamp=hour_a, request_id="a1"))
    writer.write(_event(cost=0.02, timestamp=hour_a, request_id="a2"))
    writer.write(_event(cost=0.04, timestamp=hour_b, request_id="b1"))
    writer.write(_event(cost=0.99, timestamp=outside, request_id="old"))

    series = writer.usage_timeseries(window_hours=24, bucket_hours=1, now=now)

    assert series.window_hours == 24
    assert series.bucket_hours == 1
    assert len(series.buckets) == 24
    assert series.buckets[-1].start == datetime(2026, 7, 26, 15, 0, tzinfo=UTC)
    assert series.buckets[0].start == datetime(2026, 7, 25, 16, 0, tzinfo=UTC)

    by_start = {bucket.start: bucket for bucket in series.buckets}
    assert by_start[datetime(2026, 7, 26, 13, 0, tzinfo=UTC)].request_count == 2
    assert by_start[datetime(2026, 7, 26, 13, 0, tzinfo=UTC)].estimated_cost == pytest.approx(
        0.03
    )
    assert by_start[datetime(2026, 7, 26, 14, 0, tzinfo=UTC)].request_count == 1
    assert by_start[datetime(2026, 7, 26, 14, 0, tzinfo=UTC)].estimated_cost == pytest.approx(
        0.04
    )
    assert by_start[datetime(2026, 7, 26, 15, 0, tzinfo=UTC)].request_count == 0
    assert series.total_requests == 3
    assert series.total_estimated_cost == pytest.approx(0.07)
    assert series.max_requests == 2
    assert series.max_cost == pytest.approx(0.04)


@pytest.mark.asyncio
async def test_dashboard_renders_usage_trend_panels(tmp_path: Path) -> None:
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
        _event(cost=0.012345, timestamp=now - timedelta(minutes=10), request_id="dash1")
    )
    app.state.audit_writer.write(
        _event(cost=0.01, timestamp=now - timedelta(minutes=5), request_id="dash2")
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get("/")

    assert page.status_code == 200
    assert "Usage trends" in page.text
    assert "Requests" in page.text
    assert "Estimated cost" in page.text
    assert "bar-requests" in page.text
    assert "bar-cost" in page.text
    assert "0.022345" in page.text or "Total $0.022345" in page.text
    await http_client.aclose()
