# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Helpers for privacy-safe dashboard presentation of audit events."""

from __future__ import annotations

from app.audit.models import AuditEventRow


def split_rule_ids(matched_rule_ids: str | None) -> list[str]:
    if not matched_rule_ids:
        return []
    return [part.strip() for part in matched_rule_ids.split(",") if part.strip()]


def event_detail_context(event: AuditEventRow) -> dict[str, object]:
    """Build a privacy-safe detail view: rule ids and reason, never raw secrets."""
    return {
        "event": event,
        "rule_ids": split_rule_ids(event.matched_rule_ids),
        # Explicitly omit raw_prompt / raw_response from the template context.
        "show_raw": False,
    }
