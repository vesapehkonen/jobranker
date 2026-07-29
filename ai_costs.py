from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from database import DEFAULT_DATABASE_FILE, record_ai_cost


@dataclass(frozen=True)
class TokenPrices:
    input_per_million: float
    cached_input_per_million: float
    output_per_million: float


# Standard Responses API text-token prices in USD, captured on 2026-07-28.
# Snapshot model names are handled by prefix matching below.
MODEL_PRICES = {
    "gpt-5.4-nano": TokenPrices(0.20, 0.02, 1.25),
    "gpt-5.4-mini": TokenPrices(0.75, 0.075, 4.50),
    "gpt-5.6-luna": TokenPrices(1.00, 0.10, 6.00),
    "gpt-5.6-terra": TokenPrices(2.50, 0.25, 15.00),
}


def prices_for_model(model: str) -> TokenPrices | None:
    for name, prices in MODEL_PRICES.items():
        if model == name or model.startswith(f"{name}-"):
            return prices
    return None


def _integer_attribute(value: Any, name: str) -> int:
    result = getattr(value, name, 0) if value is not None else 0
    return int(result or 0)


def track_openai_response(
    response: Any,
    operation: str,
    *,
    job_uid: str | None = None,
    profile_name: str | None = None,
    database_file: Path | str = DEFAULT_DATABASE_FILE,
) -> dict[str, Any]:
    """Persist token usage and estimated standard API cost for one response."""
    usage = getattr(response, "usage", None)
    input_tokens = _integer_attribute(usage, "input_tokens")
    output_tokens = _integer_attribute(usage, "output_tokens")
    total_tokens = _integer_attribute(usage, "total_tokens")
    if not total_tokens:
        total_tokens = input_tokens + output_tokens

    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    cached_tokens = min(
        input_tokens, _integer_attribute(input_details, "cached_tokens")
    )
    reasoning_tokens = min(
        output_tokens, _integer_attribute(output_details, "reasoning_tokens")
    )

    model = str(getattr(response, "model", "") or "")
    prices = prices_for_model(model)
    costs: dict[str, float | None] = {
        "input_cost_usd": None,
        "cached_input_cost_usd": None,
        "output_cost_usd": None,
        "total_cost_usd": None,
    }
    if prices is not None:
        costs["input_cost_usd"] = (
            (input_tokens - cached_tokens) * prices.input_per_million / 1_000_000
        )
        costs["cached_input_cost_usd"] = (
            cached_tokens * prices.cached_input_per_million / 1_000_000
        )
        costs["output_cost_usd"] = (
            output_tokens * prices.output_per_million / 1_000_000
        )
        costs["total_cost_usd"] = sum(
            value for value in costs.values() if value is not None
        )

    return record_ai_cost(
        provider="openai",
        operation=operation,
        model=model,
        response_id=getattr(response, "id", None),
        job_uid=job_uid,
        profile_name=profile_name,
        input_tokens=input_tokens,
        cached_input_tokens=cached_tokens,
        output_tokens=output_tokens,
        reasoning_output_tokens=reasoning_tokens,
        total_tokens=total_tokens,
        pricing=prices,
        database_file=database_file,
        **costs,
    )
