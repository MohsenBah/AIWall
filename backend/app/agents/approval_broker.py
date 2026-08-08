# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""In-process waiters that bridge held proxy requests to approve/deny decisions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class ApprovalBroker:
    """Maps approval ids to futures resolved by approve/deny API calls."""

    _waiters: dict[int, asyncio.Future[str]] = field(default_factory=dict)

    def register(self, approval_id: int) -> asyncio.Future[str]:
        loop = asyncio.get_running_loop()
        existing = self._waiters.get(approval_id)
        if existing is not None and not existing.done():
            return existing
        future: asyncio.Future[str] = loop.create_future()
        self._waiters[approval_id] = future
        return future

    def resolve(self, approval_id: int, decision: str) -> bool:
        future = self._waiters.pop(approval_id, None)
        if future is None or future.done():
            return False
        future.set_result(decision)
        return True

    def discard(self, approval_id: int) -> None:
        future = self._waiters.pop(approval_id, None)
        if future is not None and not future.done():
            future.cancel()

    @property
    def waiting_count(self) -> int:
        return len(self._waiters)
