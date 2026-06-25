"""Request context for policy evaluation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyContext:
    body: bytes
    model: str
    input_length: int
    contains_secret: bool = False
    estimated_cost: float = 0.0
