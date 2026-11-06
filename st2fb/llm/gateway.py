"""Every model request goes through here: cache first, then the budget check, then the client."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Callable

from .budget import Ledger
from .cache import ResponseCache, cache_key
from .client import LIVE, FatalApiError, LlmRequest, LlmResponse, ModelClient, TransientApiError
from .config import cost_usd, input_token_bound, worst_case_usd

MAX_SENDS = 3  # One request, and at most two retries of a transient failure.
_BACKOFF_S = 5.0


@dataclass(frozen=True)
class CallResult:
    response: LlmResponse
    cached: bool
    cost_usd: float  # What this response cost when it was made.
    new_spend_usd: float  # What this call spent now: 0 on a cache hit.


class Gateway:
    def __init__(
        self,
        client: ModelClient,
        ledger: Ledger,
        cache: ResponseCache,
        budget_usd: float | None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if client.kind == LIVE and budget_usd is None:
            raise ValueError("a live client needs a budget")
        if ledger.client_kind != client.kind or cache.client_kind != client.kind:
            raise ValueError("the ledger and the cache must belong to the same kind of client")
        self.client = client
        self.ledger = ledger
        self.cache = cache
        self.budget_usd = budget_usd
        self.sleep = sleep

    def call(self, request: LlmRequest, input_text: str, repeat: int, attempt: int) -> CallResult:
        key = cache_key(self.client.kind, request, input_text, repeat, attempt)
        cached = self.cache.get(key)
        if cached is not None:
            return CallResult(cached, True, cost_usd(cached.usage), 0.0)

        worst_case = worst_case_usd(request.config, input_token_bound(request.system, request.user))
        for send in range(1, MAX_SENDS + 1):
            reservation = self.ledger.reserve(worst_case, self.budget_usd, request.tag)
            try:
                response = self.client.complete(request)
            except TransientApiError as exc:
                if not exc.billed_unknown:
                    self.ledger.release(reservation, "transient API error")
                if send == MAX_SENDS:
                    raise
                self.sleep(exc.retry_after if exc.retry_after is not None else _BACKOFF_S * send)
                continue
            except FatalApiError:
                self.ledger.release(reservation, "API rejected the request")
                raise
            # Anything else, such as a reply the SDK could not parse, leaves the reservation open,
            # because the request may have been billed.
            cost = cost_usd(response.usage)
            self.ledger.settle(reservation, cost, [asdict(entry) for entry in response.usage], response.request_id)
            self.cache.put(key, request.tag, response)
            return CallResult(response, False, cost, cost)
        raise AssertionError("unreachable")
