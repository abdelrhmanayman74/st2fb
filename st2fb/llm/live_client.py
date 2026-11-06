"""The only module that imports the anthropic SDK, and only when a live client is constructed.

benchmark.py reaches this file only when --live and --budget-usd were both given.
SDK usage follows the Claude API skill's python/claude-api/README.md and shared/error-codes.md.
"""
from __future__ import annotations

from typing import Any

from .client import LIVE, FatalApiError, LlmRequest, LlmResponse, TransientApiError
from .config import FALLBACK_BETA, UsageEntry
from .keys import redact

# Fixed rather than taken from ANTHROPIC_BASE_URL, so that no stray variable can send the key elsewhere.
API_BASE_URL = "https://api.anthropic.com"
MAX_RETRY_WAIT_S = 120.0


class AnthropicClient:
    def __init__(self, api_key: str, base_url: str = API_BASE_URL, kind: str = LIVE) -> None:
        """kind exists so that a test against a local stub server can label its results as fake."""
        import anthropic  # Here, so that the rest of the project needs only the standard library.

        self.kind = kind
        self._sdk = anthropic
        self._api_key = api_key
        # max_retries=0: one SDK call is exactly one HTTP request, so that the ledger can see every
        # one of them. gateway.py does the retrying, after checking the budget again.
        self._client = anthropic.Anthropic(api_key=api_key, base_url=base_url, max_retries=0)

    def _safe(self, exc: Exception) -> str:
        return redact(f"{type(exc).__name__}: {exc}", self._api_key)

    def complete(self, request: LlmRequest) -> LlmResponse:
        sdk = self._sdk
        config = request.config
        arguments: dict[str, Any] = {}
        if config.fallbacks:
            arguments = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        try:
            message = self._client.beta.messages.create(
                model=config.model,
                max_tokens=config.max_tokens,
                output_config={"effort": config.effort},
                # The system prompt is the same for every program, so it is worth caching.
                system=[{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": request.user}],
                **arguments,
            )
        except sdk.RateLimitError as exc:
            raise TransientApiError(self._safe(exc), _retry_after(exc.response.headers)) from None
        except sdk.APIStatusError as exc:
            if exc.status_code >= 500:
                raise TransientApiError(self._safe(exc)) from None
            raise FatalApiError(self._safe(exc)) from None
        except sdk.APIConnectionError as exc:
            # This covers timeouts too: the request may have run, and been billed, on the server.
            raise TransientApiError(self._safe(exc), billed_unknown=True) from None
        return _to_response(message, config.model)


def _retry_after(headers: Any) -> float | None:
    """Seconds the server asks us to wait, capped so that a benchmark does not sleep for hours."""
    try:
        return min(float(headers.get("retry-after", "")), MAX_RETRY_WAIT_S)
    except ValueError:  # Missing, or in the HTTP-date form.
        return None


def _to_response(message: Any, requested_model: str) -> LlmResponse:
    usage = message.usage
    # Top-level usage covers only the attempt that produced the returned message. After a fallback
    # usage.iterations is the per-attempt record, and each attempt bills at its own model's rates.
    iterations = [it for it in (usage.iterations or []) if it.type in ("message", "fallback_message")]
    if iterations:
        entries = tuple(
            UsageEntry(
                it.model or requested_model,
                it.input_tokens,
                it.output_tokens,
                it.cache_creation_input_tokens,
                it.cache_read_input_tokens,
            )
            for it in iterations
        )
    else:
        entries = (
            UsageEntry(
                message.model,
                usage.input_tokens,
                usage.output_tokens,
                usage.cache_creation_input_tokens or 0,
                usage.cache_read_input_tokens or 0,
            ),
        )

    # Text produced before a fallback block belongs to the model that declined, so it is dropped.
    text_parts: list[str] = []
    for block in message.content:
        if block.type == "fallback":
            text_parts = []
        elif block.type == "text":
            text_parts.append(block.text)

    category = None
    if message.stop_reason == "refusal" and message.stop_details is not None:
        category = message.stop_details.category
    return LlmResponse(
        text="".join(text_parts),
        stop_reason=message.stop_reason,
        usage=entries,
        served_by=message.model,
        fell_back=any(it.type == "fallback_message" for it in iterations),
        refusal_category=category,
        request_id=message._request_id,
    )
