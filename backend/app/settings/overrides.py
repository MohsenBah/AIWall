# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Persist GUI settings overrides without editing the main config."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.config import AIWallConfig, LoggingConfig

OVERRIDES_FILENAME = "settings-overrides.yaml"


def settings_overrides_path(config_path: Path) -> Path:
    """Resolve the settings overrides file path.

    Prefer ``{config_dir}/data/settings-overrides.yaml`` when a data directory
    exists (Docker volume), otherwise ``{config_dir}/settings-overrides.yaml``.
    """
    data_dir = config_path.parent / "data"
    if data_dir.is_dir():
        return data_dir / OVERRIDES_FILENAME
    return config_path.parent / OVERRIDES_FILENAME


def load_settings_overrides(path: Path) -> dict[str, Any]:
    """Return a nested override dict (currently ``logging`` keys only)."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        raw: Any = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        return {}
    logging_raw = raw.get("logging")
    if not isinstance(logging_raw, dict):
        return {}
    logging_overrides: dict[str, Any] = {}
    if "log_raw_prompts" in logging_raw:
        logging_overrides["log_raw_prompts"] = bool(logging_raw["log_raw_prompts"])
    if "retention_days" in logging_raw:
        try:
            days = int(logging_raw["retention_days"])
        except (TypeError, ValueError):
            days = None
        if days is not None and days >= 1:
            logging_overrides["retention_days"] = days
    if not logging_overrides:
        return {}
    return {"logging": logging_overrides}


def apply_settings_overrides(config: AIWallConfig, overrides: dict[str, Any]) -> AIWallConfig:
    if not overrides:
        return config
    logging_overrides = overrides.get("logging")
    if not isinstance(logging_overrides, dict) or not logging_overrides:
        return config
    logging = config.logging.model_copy(update=logging_overrides)
    return config.model_copy(update={"logging": logging})


def _write_overrides(path: Path, logging_values: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"logging": dict(sorted(logging_values.items()))}
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, default_flow_style=False, sort_keys=False)
    tmp_path.replace(path)
    return path


def update_logging_settings(
    config_path: Path,
    *,
    log_raw_prompts: bool | None = None,
    retention_days: int | None = None,
    base_logging: LoggingConfig | None = None,
) -> Path:
    """Merge logging settings into the overrides file. Returns the path."""
    path = settings_overrides_path(config_path)
    current = load_settings_overrides(path).get("logging", {})
    if not isinstance(current, dict):
        current = {}
    updated = dict(current)
    if log_raw_prompts is not None:
        updated["log_raw_prompts"] = bool(log_raw_prompts)
    if retention_days is not None:
        if retention_days < 1:
            raise ValueError("retention_days must be >= 1")
        updated["retention_days"] = int(retention_days)
    if not updated and base_logging is not None:
        # Nothing to write.
        return path
    return _write_overrides(path, updated)
