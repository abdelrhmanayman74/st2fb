"""Model choice, the one price table, and what a request can cost.

Prices are as cached in the Claude API skill on 2026-10-06. They only estimate. A real cost figure
comes from the token counts in response.usage multiplied by the current price list, so check them
against the Console before quoting one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

PRICES_AS_OF = "2026-10-06"
DEFAULT_MODEL = "claude-sonnet-5-5"
ALLOWED_MODELS = ("claude-sonnet-5-5", "claude-opus-5-5")
DEFAULT_EFFORT = "medium"  # The skill's starting point for coding on Sonnet 5.5, and Opus 5.5's API default.
EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_MAX_TOKENS = 16000  # Thinking counts toward this.
# Above this, anthropic 2.6.0 refuses a non-streaming request, since it may take over ten minutes.
MAX_NON_STREAMING_TOKENS = 21333
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input: float
    output: float
    cache_write: float  # 5-minute TTL
    cache_read: float


# Sonnet 5 and the two older Opus models are here only because server-side fallback can run them.
PRICES = {
    "claude-sonnet-5-5": Price(2.00, 10.00, 2.50, 0.20),
    "claude-opus-5-5": Price(4.00, 20.00, 5.00, 0.20),
    "claude-sonnet-5": Price(2.00, 10.00, 2.50, 0.20),
    "claude-opus-5": Price(5.00, 25.00, 6.25, 0.50),
    "claude-opus-4-8": Price(5.00, 25.00, 6.25, 0.50),
}
# The dearest model each one can fall back to, per the skill's migration guide.
FALLBACK_WORST_CASE = {"claude-sonnet-5-5": "claude-sonnet-5", "claude-opus-5-5": "claude-opus-4-8"}
_DEAREST = Price(*(max(getattr(p, f) for p in PRICES.values()) for f in ("input", "output", "cache_write", "cache_read")))


@dataclass(frozen=True)
class LlmConfig:
    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    max_tokens: int = DEFAULT_MAX_TOKENS
    fallbacks: bool = True

    def __post_init__(self) -> None:
        if self.model not in ALLOWED_MODELS:
            raise ValueError(f"model must be one of {ALLOWED_MODELS}, got {self.model!r}")
        if self.effort not in EFFORTS:
            raise ValueError(f"effort must be one of {EFFORTS}, got {self.effort!r}")
        if not 0 < self.max_tokens <= MAX_NON_STREAMING_TOKENS:
            raise ValueError(f"max_tokens must be between 1 and {MAX_NON_STREAMING_TOKENS}, got {self.max_tokens}")


@dataclass(frozen=True)
class UsageEntry:
    """Tokens of one attempt. A request that fell back has one entry per model that ran."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


def entry_cost_usd(entry: UsageEntry) -> float:
    # A model missing from the table costs as much as the dearest one, rather than nothing.
    price = PRICES.get(entry.model, _DEAREST)
    return (
        entry.input_tokens * price.input
        + entry.output_tokens * price.output
        + entry.cache_creation_input_tokens * price.cache_write
        + entry.cache_read_input_tokens * price.cache_read
    ) / 1_000_000


def cost_usd(entries: Iterable[UsageEntry]) -> float:
    return sum(entry_cost_usd(entry) for entry in entries)


def input_token_bound(*texts: str) -> int:
    """An upper bound on input tokens with no tokenizer: one token per UTF-8 byte at most."""
    return sum(len(text.encode("utf-8")) for text in texts)


def worst_case_usd(config: LlmConfig, input_tokens: int) -> float:
    """The most one request can cost: all input billed as a cache write and all of max_tokens used.

    With fallbacks on, a decline can come after the first model has used all its output, and then
    the fallback model runs the same request, so both attempts are counted.
    """
    models = [config.model]
    if config.fallbacks:
        models.append(FALLBACK_WORST_CASE[config.model])
    total = 0.0
    for model in models:
        price = PRICES[model]
        total += (input_tokens * max(price.input, price.cache_write) + config.max_tokens * price.output) / 1_000_000
    return total
