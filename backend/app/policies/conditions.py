# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Evaluate policy `when` expressions."""

from __future__ import annotations

import re

from app.policies.context import PolicyContext

_COMPARISON = re.compile(
    r"^(input\.length|estimated_cost)\s*(>|<|>=|<=|==)\s*([\d.]+)$"
)
_USER_ROLE = re.compile(
    r'^user\.role\s*(==|!=)\s*["\']([^"\']+)["\']$'
)
_AND_SPLIT = re.compile(r"\s+and\s+", flags=re.IGNORECASE)


def evaluate_condition(when: str, context: PolicyContext) -> bool:
    expression = when.strip()
    if not expression:
        raise ValueError("Empty policy condition")

    parts = [part.strip() for part in _AND_SPLIT.split(expression) if part.strip()]
    if len(parts) > 1:
        return all(_evaluate_atomic(part, context) for part in parts)
    return _evaluate_atomic(expression, context)


def _evaluate_atomic(expression: str, context: PolicyContext) -> bool:
    if expression == "input.contains_secret":
        return context.contains_secret

    if expression == "input.contains_private_key":
        return context.contains_private_key

    role_match = _USER_ROLE.match(expression)
    if role_match:
        operator, expected = role_match.groups()
        actual = context.user_role
        if operator == "==":
            return actual == expected
        return actual != expected

    match = _COMPARISON.match(expression)
    if match:
        left_name, operator, raw_value = match.groups()
        left_value = (
            float(context.input_length)
            if left_name == "input.length"
            else context.estimated_cost
        )
        right_value = float(raw_value)
        return _compare(left_value, operator, right_value)

    raise ValueError(f"Unsupported policy condition: {expression}")


def _compare(left: float, operator: str, right: float) -> bool:
    if operator == ">":
        return left > right
    if operator == "<":
        return left < right
    if operator == ">=":
        return left >= right
    if operator == "<=":
        return left <= right
    if operator == "==":
        return left == right
    raise ValueError(f"Unsupported operator: {operator}")
