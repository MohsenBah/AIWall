from pathlib import Path

from app.proxy.pricing import CostEstimator
from app.proxy.tokens import TokenUsage


def test_cost_estimator_returns_cost_for_known_model(tmp_path: Path) -> None:
    prices_path = tmp_path / "prices.yaml"
    prices_path.write_text(
        """
models:
  openai:
    gpt-4o-mini:
      input_per_million: 0.15
      output_per_million: 0.60
""".strip()
    )
    estimator = CostEstimator(prices_path)
    usage = TokenUsage(prompt_tokens=1_000_000, completion_tokens=1_000_000, total_tokens=2_000_000)

    estimate = estimator.estimate("openai", "gpt-4o-mini", usage)

    assert estimate is not None
    assert estimate.estimated_cost == 0.75


def test_cost_estimator_returns_none_for_unknown_model(tmp_path: Path) -> None:
    prices_path = tmp_path / "prices.yaml"
    prices_path.write_text(
        """
models:
  openai:
    gpt-4o-mini:
      input_per_million: 0.15
      output_per_million: 0.60
""".strip()
    )
    estimator = CostEstimator(prices_path)
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)

    assert estimator.estimate("openai", "unknown-model", usage) is None
    assert estimator.estimate("ollama", "llama3.2:1b", usage) is None
