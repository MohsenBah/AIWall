# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Per-profile daily usage limit enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.audit.writer import AuditWriter, ProfileUsage
from app.policies.engine import PolicyResult
from app.profiles.store import Profile, ProfileStore

BILLABLE_DECISIONS = frozenset({"allow", "warn", "redact"})

DAILY_LIMIT_POLICY_ID = "daily-limit"
DAILY_LIMIT_REASON = "daily-limit"


def utc_day_start(now: datetime | None = None) -> datetime:
    """Start of the current UTC calendar day (daily reset boundary)."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    else:
        current = current.astimezone(UTC)
    return current.replace(hour=0, minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class DailyLimitCheck:
    exceeded: bool
    result: PolicyResult | None = None
    usage: ProfileUsage | None = None


def check_daily_limits(
    *,
    profile_store: ProfileStore,
    audit_writer: AuditWriter,
    profile_id: int | None,
    projected_tokens: int = 0,
    projected_cost: float = 0.0,
    now: datetime | None = None,
) -> DailyLimitCheck:
    """Return a block result when the profile has exhausted a configured daily cap.

    Counts billable audit decisions (`allow`/`warn`/`redact`) since UTC midnight.
    Token and cost caps also include the projected usage for the current request.
    """
    if profile_id is None:
        return DailyLimitCheck(exceeded=False)

    profile = profile_store.get(profile_id)
    if profile is None or not profile.enabled:
        return DailyLimitCheck(exceeded=False)

    if not _has_any_limit(profile):
        return DailyLimitCheck(exceeded=False)

    since = utc_day_start(now)
    usage = audit_writer.usage_for_user(
        str(profile_id),
        since=since,
        decisions=BILLABLE_DECISIONS,
    )

    request_limit = profile.daily_request_limit
    if request_limit is not None and usage.request_count >= request_limit:
        return DailyLimitCheck(
            exceeded=True,
            result=PolicyResult(
                action="block",
                policy_id=DAILY_LIMIT_POLICY_ID,
                reason=DAILY_LIMIT_REASON,
            ),
            usage=usage,
        )

    if profile.daily_token_limit is not None and _exceeds_cap(
        usage.total_tokens,
        max(0, projected_tokens),
        profile.daily_token_limit,
    ):
        return DailyLimitCheck(
            exceeded=True,
            result=PolicyResult(
                action="block",
                policy_id=DAILY_LIMIT_POLICY_ID,
                reason=DAILY_LIMIT_REASON,
            ),
            usage=usage,
        )

    if profile.daily_cost_limit is not None and _exceeds_cap(
        usage.estimated_cost,
        max(0.0, projected_cost),
        profile.daily_cost_limit,
    ):
        return DailyLimitCheck(
            exceeded=True,
            result=PolicyResult(
                action="block",
                policy_id=DAILY_LIMIT_POLICY_ID,
                reason=DAILY_LIMIT_REASON,
            ),
            usage=usage,
        )

    return DailyLimitCheck(exceeded=False, usage=usage)


def _exceeds_cap(used: float, projected: float, limit: float) -> bool:
    """True when prior usage is already at/over the cap, or this request would exceed it."""
    if used >= limit:
        return True
    return projected > 0 and (used + projected) > limit


def _has_any_limit(profile: Profile) -> bool:
    return (
        profile.daily_request_limit is not None
        or profile.daily_token_limit is not None
        or profile.daily_cost_limit is not None
    )
