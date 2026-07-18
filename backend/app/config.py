# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Load and validate AIWall configuration from aiwall.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path("aiwall.yaml")
CONFIG_ENV_VAR = "AIWALL_CONFIG"


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class ProviderConfig(BaseModel):
    name: str
    type: str
    base_url: str
    api_key_env: str | None = None
    models: list[str] = Field(default_factory=list)


class PolicyConfig(BaseModel):
    name: str
    when: str
    action: str
    enabled: bool = True


class LoggingConfig(BaseModel):
    store: str = "sqlite:///data/aiwall.db"
    log_raw_prompts: bool = False
    retention_days: int = 90


class PricingConfig(BaseModel):
    file: str = "prices.yaml"


class GatewayAuthConfig(BaseModel):
    enabled: bool = False
    api_key_env: str = "AIWALL_API_KEY"


class EntropyScannerConfig(BaseModel):
    enabled: bool = True
    min_length: int = 20
    threshold: float = 4.5


class DotenvScannerConfig(BaseModel):
    enabled: bool = True
    min_lines: int = 2
    min_value_length: int = 8
    pasted_file_min_lines: int = 5


class RuleScannerConfig(BaseModel):
    enabled: bool = True
    min_length: int | None = None


class ScannerAllowlistConfig(BaseModel):
    literals: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)


class ScannerConfig(BaseModel):
    entropy: EntropyScannerConfig = Field(default_factory=EntropyScannerConfig)
    dotenv: DotenvScannerConfig = Field(default_factory=DotenvScannerConfig)
    ignore_examples: bool = True
    allowlist: ScannerAllowlistConfig = Field(default_factory=ScannerAllowlistConfig)
    rules: dict[str, RuleScannerConfig] = Field(default_factory=dict)


class AIWallConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    providers: list[ProviderConfig] = Field(default_factory=list)
    presets: list[str] = Field(default_factory=list)
    policies: list[PolicyConfig] = Field(default_factory=list)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    pricing: PricingConfig = Field(default_factory=PricingConfig)
    gateway_auth: GatewayAuthConfig = Field(default_factory=GatewayAuthConfig)
    scanners: ScannerConfig = Field(default_factory=ScannerConfig)


def resolve_config_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    env_path = os.environ.get(CONFIG_ENV_VAR)
    if env_path:
        return Path(env_path)
    return DEFAULT_CONFIG_PATH


def load_config(path: Path | str | None = None) -> AIWallConfig:
    config_path = resolve_config_path(path)
    if not config_path.exists():
        return AIWallConfig()

    with config_path.open(encoding="utf-8") as config_file:
        raw: Any = yaml.safe_load(config_file) or {}

    config = AIWallConfig.model_validate(raw)
    if not config.presets:
        return config

    from app.presets import merge_preset_policies

    merged_policies = merge_preset_policies(
        config.presets,
        config.policies,
        config_dir=config_path.parent,
    )
    return config.model_copy(update={"policies": merged_policies})


def reload_config(app_config_path: Path | str | None) -> AIWallConfig:
    """Reload configuration from disk. Used by future hot-reload paths."""
    return load_config(app_config_path)
