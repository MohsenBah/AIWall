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


class AIWallConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    providers: list[ProviderConfig] = Field(default_factory=list)
    policies: list[PolicyConfig] = Field(default_factory=list)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


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

    return AIWallConfig.model_validate(raw)


def reload_config(app_config_path: Path | str | None) -> AIWallConfig:
    """Reload configuration from disk. Used by future hot-reload paths."""
    return load_config(app_config_path)
