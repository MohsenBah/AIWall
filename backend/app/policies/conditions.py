"""Evaluate policy `when` expressions."""

from __future__ import annotations

import re

from app.policies.context import PolicyContext

_COMPARISON = re.compile(
    r"^(input\.length|estimated_cost)\s*(>|<|>=|<=|==)\s*([\d.]+)$"
)


def evaluate_condition(when: str, context: PolicyContext) -> bool:
    expression = when.strip()

    if expression == "input.contains_secret":
        return context.contains_secret

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

    raise ValueError(f"Unsupported policy condition: {when}")


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
