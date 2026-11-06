"""One migration of one program: generate, run on the tuning stimulus, and repair if the mode allows.

This module is only ever given the tuning stimulus. The held-out score is taken afterwards by
benchmark.py on whatever candidate this returns, so no feedback can carry held-out information.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import fbt, forte_eval
from . import prompts
from .budget import BudgetExceeded
from .client import FatalApiError, LlmRequest, TransientApiError
from .config import LlmConfig
from .gateway import CallResult, Gateway

MODE_ATTEMPTS = {"llm_only": 1, "llm_repair": 3}
FAILURE_LIMIT = 4000  # Largest failure description worth paying to send back.
_INPUT_CONTEXT_SCANS = 3

CATEGORY_OF_STATUS = {
    "parse_failed": "xml_error",
    "plan_failed": "interface_error",
    "compile_failed": "compile_error",
    "crashed": "runtime_error",
    "timed_out": "runtime_error",
    "different": "tuning_different",
    "infra_failed": "infra_error",
}


@dataclass(frozen=True)
class ProgramInput:
    """All that a model-facing run may see of a program. There is no held-out field, on purpose."""

    name: str
    source: str
    tuning_path: Path
    tuning_trace: dict[str, Any]


@dataclass
class AttemptRecord:
    attempt: int
    stop_reason: str
    status: str | None  # forte_eval status, or None when no candidate was evaluated.
    call: CallResult | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        response = self.call.response if self.call else None
        return {
            "attempt": self.attempt,
            "stop_reason": self.stop_reason,
            "status": self.status,
            "detail": self.detail,
            "cached": bool(self.call and self.call.cached),
            "cost_usd": self.call.cost_usd if self.call else 0.0,
            "new_spend_usd": self.call.new_spend_usd if self.call else 0.0,
            "served_by": response.served_by if response else None,
            "fell_back": bool(response and response.fell_back),
            "refusal_category": response.refusal_category if response else None,
            "usage": [vars(entry) for entry in response.usage] if response else [],
        }


@dataclass
class MigrationResult:
    attempts: list[AttemptRecord] = field(default_factory=list)
    candidate: str | None = None  # The last .fbt evaluated.
    tuning_status: str | None = None
    tuning_first_divergence: dict[str, Any] | None = None
    failure_category: str | None = None
    stop_run: str | None = None  # Set when the whole benchmark must stop: budget or API failure.

    @property
    def tuning_equal(self) -> bool:
        return self.tuning_status == "equal"


def extract_fbt(text: str) -> str:
    """The FBType document in a reply, tolerating a Markdown fence or stray prose around it."""
    match = re.search(r"(<\?xml.*?\?>\s*)?<FBType\b.*</FBType>", text, flags=re.DOTALL)
    return match.group(0) if match else text.strip()


def describe_failure(outcome: forte_eval.Outcome, stimulus: dict[str, Any]) -> str:
    """Turn a failed tuning run into text for the next attempt: the concrete failure and no more."""
    if outcome.status == "parse_failed":
        return f"The file is not valid: {outcome.detail}"
    if outcome.status == "plan_failed":
        return f"The file breaks the interface contract: {outcome.detail}"
    if outcome.status == "compile_failed":
        return f"The exporter or the C++ compiler rejected it:\n{outcome.detail}"[:FAILURE_LIMIT]
    if outcome.status == "timed_out":
        return f"It ran, but a REQ never produced CNF: {outcome.detail}"[:FAILURE_LIMIT]
    if outcome.status == "crashed":
        return f"The FORTE run failed: {outcome.detail}"[:FAILURE_LIMIT]
    report = outcome.report or {}
    first = report.get("first_divergence") or {}
    lines = [
        "It ran, and an output differs from the reference.",
        f"First divergence: scan {first.get('scan')} (t = {first.get('t_ms')} ms), output {first.get('output')}: "
        f"expected {json.dumps(first.get('expected'))}, got {json.dumps(first.get('actual'))}.",
        f"Total divergences: {report.get('divergences')} over {report.get('scans_compared')} scans.",
    ]
    if report.get("shape_errors"):
        lines.append(f"Structural problems: {report['shape_errors']}")
    scan = first.get("scan")
    if isinstance(scan, int) and scan < len(stimulus["scans"]):
        lines.append("Inputs on the scans leading to it:")
        for index in range(max(0, scan - _INPUT_CONTEXT_SCANS), scan + 1):
            lines.append(f"  scan {index}: {json.dumps(stimulus['scans'][index])}")
    return "\n".join(lines)[:FAILURE_LIMIT]


def migrate(program: ProgramInput, mode: str, config: LlmConfig, gateway: Gateway, repeat: int) -> MigrationResult:
    result = MigrationResult()
    system = prompts.system_prompt()
    stimulus = json.loads(program.tuning_path.read_text(encoding="utf-8"))
    user = prompts.generate_prompt(program.source)

    for attempt in range(1, MODE_ATTEMPTS[mode] + 1):
        tag = f"{program.name}/{mode}/{config.model}/r{repeat}/a{attempt}"
        request = LlmRequest(system=system, user=user, config=config, tag=tag)
        try:
            call = gateway.call(request, program.source, repeat, attempt)
        except BudgetExceeded as exc:
            result.failure_category, result.stop_run = "budget_stop", f"budget: {exc}"
            return result
        except (FatalApiError, TransientApiError) as exc:
            result.failure_category, result.stop_run = "api_error", f"API error: {exc}"
            return result
        response = call.response

        # Checked before the content is touched. A refusal or a truncated reply would most likely
        # come back the same if it were sent again, at the same price, so neither gets a repair attempt.
        if response.stop_reason != "end_turn":
            category = response.stop_reason if response.stop_reason in ("refusal", "max_tokens") else "bad_stop_reason"
            result.attempts.append(AttemptRecord(attempt, response.stop_reason, None, call))
            result.failure_category = category
            return result

        candidate = extract_fbt(response.text)
        outcome = forte_eval.evaluate(candidate, program.tuning_path, program.tuning_trace)
        result.candidate = candidate
        result.tuning_status = outcome.status
        result.tuning_first_divergence = outcome.report["first_divergence"] if outcome.report else None
        result.attempts.append(AttemptRecord(attempt, response.stop_reason, outcome.status, call, outcome.detail[:500]))
        if outcome.equal:
            result.failure_category = None
            return result
        result.failure_category = CATEGORY_OF_STATUS[outcome.status]
        if outcome.status == "infra_failed":  # Not the model's fault, so it gets no repair prompt.
            return result
        user = prompts.repair_prompt(program.source, candidate, describe_failure(outcome, stimulus))
    return result


def ecc_structure(candidate: str) -> dict[str, Any]:
    """State counts, so that structure can be reported next to correctness.

    A working state is one with an action. START -> RUN -> START has one, which is a wrapper around the
    original scan: possibly correct, but not restructured.
    """
    try:
        fb = fbt.parse_fbt(candidate)
    except (ValueError, TypeError):
        return {"ecc_states": None, "working_states": None, "algorithms": None, "restructured": None}
    working = sum(1 for state in fb.states if state.actions)
    return {
        "ecc_states": len(fb.states),
        "working_states": working,
        "algorithms": len(fb.algorithms),
        "restructured": working >= 2,
    }
