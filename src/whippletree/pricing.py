"""Fallback cost when the provider doesn't report one. OpenRouter reports its own."""

from whippletree.providers.base import parse_model

# "provider:model" -> (USD per million input tokens, USD per million output tokens).
# Add an entry when benchmarking a model whose provider doesn't report cost.
PRICES: dict[str, tuple[float, float]] = {}

FREE_PROVIDERS = {"ollama"}


def estimate(model_spec: str, input_tokens: int, output_tokens: int) -> float | None:
    provider, _ = parse_model(model_spec)
    if provider in FREE_PROVIDERS:
        return 0.0
    price = PRICES.get(model_spec)
    if price is None:
        return None
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000
