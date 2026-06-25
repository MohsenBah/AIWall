"""Persist audit events to SQLite."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.engine import Engine

from app.audit.models import AuditEventRow
from app.storage.database import session_factory


@dataclass(frozen=True)
class AuditEvent:
    request_id: str
    provider: str
    model: str
    decision: str
    reason: str | None
    input_length: int
    output_length: int
    latency_ms: float
    user_id: str | None = None
    app_id: str | None = None
    estimated_cost: float | None = None
    policy_id: str | None = None
    raw_prompt: str | None = None
    raw_response: str | None = None
    timestamp: datetime | None = None


class AuditWriter:
    def __init__(self, engine: Engine):
        self._engine = engine
        self._session_factory = session_factory(engine)

    def write(self, event: AuditEvent) -> AuditEventRow:
        row = AuditEventRow(
            timestamp=event.timestamp or datetime.now(timezone.utc),
            request_id=event.request_id,
            user_id=event.user_id,
            app_id=event.app_id,
            provider=event.provider,
            model=event.model,
            decision=event.decision,
            reason=event.reason,
            input_length=event.input_length,
            output_length=event.output_length,
            estimated_cost=event.estimated_cost,
            policy_id=event.policy_id,
            latency_ms=event.latency_ms,
            raw_prompt=event.raw_prompt,
            raw_response=event.raw_response,
        )
        with self._session_factory() as session:
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def list_recent(self, limit: int = 100) -> list[AuditEventRow]:
        from sqlalchemy import select

        with self._session_factory() as session:
            stmt = select(AuditEventRow).order_by(AuditEventRow.id.desc()).limit(limit)
            return list(session.scalars(stmt).all())
