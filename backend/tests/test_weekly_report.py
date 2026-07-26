# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine

from app.audit.writer import AuditEvent, AuditWriter
from app.profiles.store import ProfileStore
from app.reports.weekly import build_weekly_report, render_markdown
from app.storage.database import init_db

pytest.importorskip("jinja2")


def _stores(tmp_path: Path) -> tuple[AuditWriter, ProfileStore]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'report.db').as_posix()}")
    init_db(engine)
    return AuditWriter(engine), ProfileStore(engine)


def test_build_weekly_report_per_profile_summary(tmp_path: Path) -> None:
    writer, store = _stores(tmp_path)
    child = store.create(name="Kid", role="child")
    adult = store.create(name="Parent", role="adult")
    now = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    since = now - timedelta(days=7)

    writer.write(
        AuditEvent(
            request_id="c1",
            provider="openai",
            model="gpt-4o-mini",
            decision="block",
            reason="category-blocked",
            input_length=10,
            output_length=0,
            latency_ms=1.0,
            user_id=str(child.id),
            categories="explicit",
            timestamp=since + timedelta(days=1),
        )
    )
    writer.write(
        AuditEvent(
            request_id="c2",
            provider="openai",
            model="gpt-4o-mini",
            decision="allow",
            reason="proxied",
            input_length=10,
            output_length=5,
            latency_ms=1.0,
            user_id=str(child.id),
            total_tokens=40,
            estimated_cost=0.01,
            timestamp=since + timedelta(days=2),
        )
    )
    writer.write(
        AuditEvent(
            request_id="a1",
            provider="openai",
            model="gpt-4o-mini",
            decision="allow",
            reason="proxied",
            input_length=10,
            output_length=5,
            latency_ms=1.0,
            user_id=str(adult.id),
            total_tokens=100,
            estimated_cost=0.05,
            timestamp=since + timedelta(days=3),
        )
    )
    # Outside the weekly window — must not count.
    writer.write(
        AuditEvent(
            request_id="old",
            provider="openai",
            model="gpt-4o-mini",
            decision="block",
            reason="category-blocked",
            input_length=10,
            output_length=0,
            latency_ms=1.0,
            user_id=str(child.id),
            categories="unsafe",
            timestamp=since - timedelta(days=1),
        )
    )

    report = build_weekly_report(writer, store, now=now, days=7)
    by_name = {p.name: p for p in report.profiles}

    assert report.window_start == since
    assert report.window_end == now
    assert set(by_name) == {"Kid", "Parent"}

    kid = by_name["Kid"]
    assert kid.request_count == 2
    assert kid.block_count == 1
    assert kid.total_tokens == 40
    assert kid.estimated_cost == pytest.approx(0.01)
    assert kid.categories == {"explicit": 1}

    parent = by_name["Parent"]
    assert parent.request_count == 1
    assert parent.block_count == 0
    assert parent.total_tokens == 100
    assert parent.estimated_cost == pytest.approx(0.05)
    assert parent.categories == {}

    assert report.total_requests == 3
    assert report.total_blocks == 1
    assert report.total_estimated_cost == pytest.approx(0.06)

    markdown = render_markdown(report)
    assert "# Weekly family report" in markdown
    assert "## Kid (child)" in markdown
    assert "## Parent (adult)" in markdown
    assert "`explicit`: 1" in markdown
    assert "Total blocks: 1" in markdown


@pytest.mark.asyncio
async def test_weekly_report_page_html_and_markdown(tmp_path, monkeypatch) -> None:
    import httpx

    from app.main import create_app
    from tests.conftest import write_test_config

    monkeypatch.setenv("OPENAI_API_KEY", "upstream-openai-key")
    config_path = write_test_config(tmp_path, policies_block="")
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    )
    app = create_app(config_path=config_path, http_client=http_client)

    child = app.state.profile_store.create(name="ReportKid", role="child")
    app.state.audit_writer.write(
        AuditEvent(
            request_id="web1",
            provider="openai",
            model="gpt-4o-mini",
            decision="block",
            reason="category-blocked",
            input_length=5,
            output_length=0,
            latency_ms=1.0,
            user_id=str(child.id),
            categories="violence",
            estimated_cost=0.0,
            total_tokens=0,
        )
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        html = await client.get("/reports/weekly")
        md = await client.get("/reports/weekly", params={"format": "md"})

    assert html.status_code == 200
    assert "Weekly family report" in html.text
    assert "ReportKid" in html.text
    assert "violence" in html.text
    assert "Download Markdown" in html.text

    assert md.status_code == 200
    assert "text/markdown" in md.headers["content-type"]
    assert "## ReportKid (child)" in md.text
    assert "`violence`: 1" in md.text
    await http_client.aclose()
