# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Load named policy presets shipped with AIWall."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.config import PolicyConfig

PRIVATE_KEY_RULE_IDS = frozenset(
    {
        "ssh-private-key",
        "pkcs8-private-key",
        "encrypted-private-key",
    }
)

_PACKAGE_PRESETS_DIR = Path(__file__).resolve().parent


def resolve_preset_path(name: str, config_dir: Path | None = None) -> Path:
    """Resolve a preset YAML path.

    Search order:
    1. ``{config_dir}/presets/{name}.yaml``
    2. package-shipped ``app/presets/{name}.yaml``
    3. repo-root ``presets/{name}.yaml`` (when running from a source checkout)
    """
    safe_name = Path(name).name
    if safe_name != name or "/" in name or "\\" in name:
        raise ValueError(f"Invalid preset name: {name}")

    candidates: list[Path] = []
    if config_dir is not None:
        candidates.append(config_dir / "presets" / f"{safe_name}.yaml")
    candidates.append(_PACKAGE_PRESETS_DIR / f"{safe_name}.yaml")
    # backend/app/presets -> repo root presets/
    candidates.append(_PACKAGE_PRESETS_DIR.parents[3] / "presets" / f"{safe_name}.yaml")

    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(f"Policy preset not found: {name}")


def load_preset_policies(name: str, config_dir: Path | None = None) -> list[PolicyConfig]:
    path = resolve_preset_path(name, config_dir)
    with path.open(encoding="utf-8") as preset_file:
        raw: Any = yaml.safe_load(preset_file) or {}

    policies_raw = raw.get("policies")
    if not isinstance(policies_raw, list):
        raise ValueError(f"Preset {name!r} must contain a policies list")

    return [PolicyConfig.model_validate(item) for item in policies_raw]


def merge_preset_policies(
    preset_names: list[str],
    policies: list[PolicyConfig],
    config_dir: Path | None = None,
) -> list[PolicyConfig]:
    """Expand named presets, then append/override with explicit policies."""
    if not preset_names:
        return list(policies)

    merged: list[PolicyConfig] = []
    index_by_name: dict[str, int] = {}

    for name in preset_names:
        for policy in load_preset_policies(name, config_dir):
            if policy.name in index_by_name:
                merged[index_by_name[policy.name]] = policy
            else:
                index_by_name[policy.name] = len(merged)
                merged.append(policy)

    for policy in policies:
        if policy.name in index_by_name:
            merged[index_by_name[policy.name]] = policy
        else:
            index_by_name[policy.name] = len(merged)
            merged.append(policy)

    return merged


def has_private_key_rule(rule_ids: tuple[str, ...] | list[str]) -> bool:
    return any(rule_id in PRIVATE_KEY_RULE_IDS for rule_id in rule_ids)
