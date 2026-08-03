# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Persist GUI policy enable/disable overrides without editing the main config."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.config import PolicyConfig

OVERRIDES_FILENAME = "policy-overrides.yaml"


def policy_overrides_path(config_path: Path) -> Path:
    """Resolve the overrides file path.

    Prefer ``{config_dir}/data/policy-overrides.yaml`` when a data directory
    exists (Docker volume), otherwise ``{config_dir}/policy-overrides.yaml``.
    """
    data_dir = config_path.parent / "data"
    if data_dir.is_dir():
        return data_dir / OVERRIDES_FILENAME
    return config_path.parent / OVERRIDES_FILENAME


def load_policy_overrides(path: Path) -> dict[str, bool]:
    """Return ``{policy_name: enabled}`` from an overrides file."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        raw: Any = yaml.safe_load(handle) or {}
    policies = raw.get("policies")
    if not isinstance(policies, dict):
        return {}

    enabled_by_name: dict[str, bool] = {}
    for name, value in policies.items():
        if not isinstance(name, str):
            continue
        if isinstance(value, bool):
            enabled_by_name[name] = value
        elif isinstance(value, dict) and "enabled" in value:
            enabled_by_name[name] = bool(value["enabled"])
    return enabled_by_name


def apply_policy_overrides(
    policies: list[PolicyConfig],
    overrides: dict[str, bool],
) -> list[PolicyConfig]:
    if not overrides:
        return list(policies)
    return [
        policy.model_copy(update={"enabled": overrides[policy.name]})
        if policy.name in overrides
        else policy
        for policy in policies
    ]


def set_policy_enabled(config_path: Path, policy_name: str, enabled: bool) -> Path:
    """Write ``enabled`` for ``policy_name`` into the overrides file. Returns the path."""
    path = policy_overrides_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_policy_overrides(path)
    current[policy_name] = enabled
    payload = {
        "policies": {
            name: {"enabled": value} for name, value in sorted(current.items())
        }
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, default_flow_style=False, sort_keys=False)
    tmp_path.replace(path)
    return path
