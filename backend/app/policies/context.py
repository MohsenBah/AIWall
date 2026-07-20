# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Request context for policy evaluation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyContext:
    body: bytes
    model: str
    input_length: int
    contains_secret: bool = False
    contains_private_key: bool = False
    estimated_cost: float = 0.0
    user_role: str | None = None
    user_id: str | None = None
