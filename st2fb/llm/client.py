"""What the benchmark needs from a model client, and the fake one the tests and a non-live run use.

A real response only ever comes from live_client.py, which is the one module that imports the SDK.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from .config import LlmConfig, UsageEntry

FAKE, LIVE = "fake", "live"


@dataclass(frozen=True)
class LlmRequest:
    system: str
    user: str
    config: LlmConfig
    tag: str = ""  # Who is asking, as program/mode/repeat/attempt. Never sent to the API.


@dataclass(frozen=True)
class LlmResponse:
    text: str
    stop_reason: str
    usage: tuple[UsageEntry, ...]
    served_by: str
    fell_back: bool = False
    refusal_category: str | None = None
    request_id: str | None = None


class TransientApiError(Exception):
    """Worth retrying: 429, 5xx, or a connection failure. billed_unknown: the request may have run."""

    def __init__(self, message: str, retry_after: float | None = None, billed_unknown: bool = False) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.billed_unknown = billed_unknown


class FatalApiError(Exception):
    """Retrying cannot help: bad request, bad key, no credit, unknown model."""


class ModelClient(Protocol):
    kind: str

    def complete(self, request: LlmRequest) -> LlmResponse: ...


@dataclass(frozen=True)
class FakeReply:
    """One scripted answer. The token counts are invented, like everything else about it."""

    text: str = ""
    stop_reason: str = "end_turn"
    input_tokens: int = 1000
    output_tokens: int = 1000
    refusal_category: str | None = None
    raises: Exception | None = None


class FakeClient:
    """Answers from a script. It never touches the network and everything it produces is labelled fake.

    script: one reply per request, in order, or a function from the request to a reply.
    """

    kind = FAKE

    def __init__(self, script: Sequence[FakeReply] | Callable[[LlmRequest], FakeReply]) -> None:
        self.script = script
        self.requests: list[LlmRequest] = []

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        if callable(self.script):
            reply = self.script(request)
        else:
            if len(self.requests) > len(self.script):
                raise AssertionError(f"fake client ran out of replies at request {len(self.requests)}: {request.tag}")
            reply = self.script[len(self.requests) - 1]
        if reply.raises is not None:
            raise reply.raises
        model = request.config.model
        return LlmResponse(
            text=reply.text,
            stop_reason=reply.stop_reason,
            usage=(UsageEntry(model, reply.input_tokens, reply.output_tokens),),
            served_by=model,
            refusal_category=reply.refusal_category,
            request_id=f"fake-{len(self.requests)}",
        )
