# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Persist audit events to SQLite."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

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
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    policy_id: str | None = None
    raw_prompt: str | None = None
    raw_response: str | None = None
    timestamp: datetime | None = None


@dataclass(frozen=True)
class AuditSummary:
    window_hours: int
    total: int = 0
    decision_counts: dict[str, int] = field(default_factory=dict)
    total_estimated_cost: float = 0.0

    @property
    def allow(self) -> int:
        return self.decision_counts.get("allow", 0)

    @property
    def warn(self) -> int:
        return self.decision_counts.get("warn", 0)

    @property
    def block(self) -> int:
        return self.decision_counts.get("block", 0)

    @property
    def error(self) -> int:
        return self.decision_counts.get("error", 0)


class AuditWriter:
    def __init__(self, engine: Engine):
        self._engine = engine
        self._session_factory = session_factory(engine)

    def write(self, event: AuditEvent) -> AuditEventRow:
        row = AuditEventRow(
            timestamp=event.timestamp or datetime.now(UTC),
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
            prompt_tokens=event.prompt_tokens,
            completion_tokens=event.completion_tokens,
            total_tokens=event.total_tokens,
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

    def list_recent(
        self,
        limit: int = 100,
        *,
        decision: str | None = None,
        provider: str | None = None,
    ) -> list[AuditEventRow]:
        from sqlalchemy import select

        with self._session_factory() as session:
            stmt = select(AuditEventRow).order_by(AuditEventRow.id.desc()).limit(limit)
            if decision:
                stmt = stmt.where(AuditEventRow.decision == decision)
            if provider:
                stmt = stmt.where(AuditEventRow.provider == provider)
            return list(session.scalars(stmt).all())

    def list_providers(self) -> list[str]:
        from sqlalchemy import select

        with self._session_factory() as session:
            stmt = select(AuditEventRow.provider).distinct().order_by(AuditEventRow.provider)
            return list(session.scalars(stmt).all())

    def summary(self, window_hours: int = 24) -> AuditSummary:
        from sqlalchemy import func, select

        since = datetime.now(UTC) - timedelta(hours=window_hours)
        with self._session_factory() as session:
            count_stmt = (
                select(AuditEventRow.decision, func.count())
                .where(AuditEventRow.timestamp >= since)
                .group_by(AuditEventRow.decision)
            )
            decision_counts = {decision: count for decision, count in session.execute(count_stmt)}

            cost_stmt = select(func.coalesce(func.sum(AuditEventRow.estimated_cost), 0.0)).where(
                AuditEventRow.timestamp >= since
            )
            total_cost = session.execute(cost_stmt).scalar_one()

        return AuditSummary(
            window_hours=window_hours,
            total=sum(decision_counts.values()),
            decision_counts=decision_counts,
            total_estimated_cost=float(total_cost or 0.0),
        )
