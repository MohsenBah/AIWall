"""Static model pricing loaded from prices.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.proxy.tokens import TokenUsage

DEFAULT_PRICES_FILENAME = "prices.yaml"


class ModelPrice(BaseModel):
    input_per_million: float
    output_per_million: float


class PricesFile(BaseModel):
    models: dict[str, dict[str, ModelPrice]] = Field(default_factory=dict)


@dataclass(frozen=True)
class CostEstimate:
    estimated_cost: float


class CostEstimator:
    def __init__(self, prices_path: Path):
        self._prices_path = prices_path
        self._prices = self._load_prices()

    def _load_prices(self) -> PricesFile:
        if not self._prices_path.exists():
            return PricesFile()
        with self._prices_path.open(encoding="utf-8") as prices_file:
            raw: Any = yaml.safe_load(prices_file) or {}
        return PricesFile.model_validate(raw)

    def estimate(
        self,
        provider_name: str,
        model: str,
        usage: TokenUsage,
    ) -> CostEstimate | None:
        provider_prices = self._prices.models.get(provider_name)
        if not provider_prices:
            return None

        model_price = provider_prices.get(model)
        if model_price is None:
            return None

        prompt_cost = (usage.prompt_tokens / 1_000_000) * model_price.input_per_million
        completion_cost = (usage.completion_tokens / 1_000_000) * model_price.output_per_million
        return CostEstimate(estimated_cost=round(prompt_cost + completion_cost, 8))

    def reload(self) -> None:
        self._prices = self._load_prices()

    def list_models(self, provider_name: str) -> list[str]:
        provider_prices = self._prices.models.get(provider_name)
        if not provider_prices:
            return []
        return list(provider_prices.keys())


def resolve_prices_path(config_path: Path, pricing_file: str) -> Path:
    prices_path = Path(pricing_file)
    if prices_path.is_absolute():
        return prices_path
    return config_path.parent / prices_path
