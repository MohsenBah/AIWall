# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text

from app.audit.writer import AuditEvent, AuditWriter
from app.storage.database import init_db
from tests.conftest import write_test_config

pytest.importorskip("jinja2")


def _writer(tmp_path: Path) -> tuple[AuditWriter, str]:
    db_path = tmp_path / "hits.db"
    url = f"sqlite:///{db_path.as_posix()}"
    engine = create_engine(url)
    init_db(engine)
    return AuditWriter(engine), url


def test_policy_hit_stats_match_sqlite(tmp_path: Path) -> None:
    writer, db_url = _writer(tmp_path)
    t1 = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 7, 26, 12, 30, tzinfo=UTC)
    t3 = datetime(2026, 7, 26, 11, 0, tzinfo=UTC)

    writer.write(
        AuditEvent(
            request_id="a",
            provider="openai",
            model="gpt-4o-mini",
            decision="block",
            reason="secret-detected",
            input_length=1,
            output_length=0,
            latency_ms=1.0,
            policy_id="block-secrets",
            timestamp=t1,
        )
    )
    writer.write(
        AuditEvent(
            request_id="b",
            provider="openai",
            model="gpt-4o-mini",
            decision="block",
            reason="secret-detected",
            input_length=1,
            output_length=0,
            latency_ms=1.0,
            policy_id="block-secrets",
            timestamp=t2,
        )
    )
    writer.write(
        AuditEvent(
            request_id="c",
            provider="openai",
            model="gpt-4o-mini",
            decision="warn",
            reason="policy_warn",
            input_length=1,
            output_length=0,
            latency_ms=1.0,
            policy_id="warn-large-cost",
            timestamp=t3,
        )
    )
    writer.write(
        AuditEvent(
            request_id="d",
            provider="openai",
            model="gpt-4o-mini",
            decision="allow",
            reason="proxied",
            input_length=1,
            output_length=0,
            latency_ms=1.0,
            policy_id=None,
            timestamp=t2,
        )
    )

    stats = writer.policy_hit_stats()
    assert set(stats) == {"block-secrets", "warn-large-cost"}
    assert stats["block-secrets"].hit_count == 2
    assert stats["block-secrets"].last_triggered == t2
    assert stats["warn-large-cost"].hit_count == 1
    assert stats["warn-large-cost"].last_triggered == t3

    engine = create_engine(db_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT policy_id, COUNT(*) AS hit_count, MAX(timestamp) AS last_triggered
                FROM audit_events
                WHERE policy_id IS NOT NULL
                GROUP BY policy_id
                """
            )
        ).all()
    sql = {policy_id: (int(count), last) for policy_id, count, last in rows}
    assert sql["block-secrets"][0] == 2
    assert sql["warn-large-cost"][0] == 1


@pytest.mark.asyncio
async def test_policies_page_shows_hit_counts(
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
        first = await client.post("/v1/chat/completions", json=long_body)
        second = await client.post("/v1/chat/completions", json=long_body)
        assert first.status_code == 403
        assert second.status_code == 403

        page = await client.get("/policies")

    assert page.status_code == 200
    assert "Hits" in page.text
    assert "Last triggered" in page.text
    assert "block-long-input" in page.text
    # Two hits for the blocking policy.
    assert ">2<" in page.text or "\n            2\n" in page.text
    stats = app.state.audit_writer.policy_hit_stats()
    assert stats["block-long-input"].hit_count == 2
    assert stats["block-long-input"].last_triggered is not None
    await http_client.aclose()
