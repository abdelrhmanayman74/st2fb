"""Benchmark LLM migration against the deterministic translator on identical inputs.

    python3 -m st2fb.llm.benchmark --dry-run --programs all --model claude-sonnet-5-5:3 claude-opus-5-5:1
    python3 -m st2fb.llm.benchmark --programs 00_latch                 # fake client, no network, no key
    python3 -m st2fb.llm.benchmark --live --budget-usd 1 --programs 00_latch --modes llm_only
    python3 -m st2fb.llm.benchmark --dry-run --corpus-dir corpus_hard/siemens_scl corpus_hard/rockwell_st   # docs/HARD_CORPUS.md
    python3 -m st2fb.llm.benchmark --dry-run --form ecc_persistent                                          # docs/HARD_CORPUS.md

Without --live, the only client that can be constructed is the fake one, which echoes the deterministic
translator's output, and results go to build/llm/fake/. Reports say which client made them.

The score is taken on heldout_stimulus.json after the migration has finished, and on heldout_stimulus_2.json too where a program
has one. A run passes only if the final candidate equals matiec on the tuning stimulus and on every held-out stimulus.

A real run on corpus_hard/ (fake or live, not --dry-run) refuses to start unless `python3 -m st2fb.llm.hard_check` has passed on
exactly these files. See manifest.py.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from .. import fbt, forte_eval, reference_run
from ..translate import translate_source
from ..vendor_frontend import to_plain_st
from . import manifest, prompts
from .budget import Ledger
from .cache import ResponseCache
from .client import FAKE, LIVE, FakeClient, FakeReply, LlmRequest, ModelClient
from .config import ALLOWED_MODELS, DEFAULT_EFFORT, DEFAULT_MAX_TOKENS, DEFAULT_MODEL, PRICES_AS_OF, LlmConfig, input_token_bound, worst_case_usd
from .ecc_metric import ecc_persistence
from .engine import FAILURE_LIMIT, MODE_ATTEMPTS, CATEGORY_OF_STATUS, MigrationResult, ProgramInput, ecc_structure, migrate
from .gateway import Gateway
from .keys import DEFAULT_ENV_FILE, ApiKeyError, load_api_key

REPO = Path(__file__).resolve().parent.parent.parent
LIVE_DIR = REPO / "build" / "llm"
FAKE_DIR = LIVE_DIR / "fake"
# The hard corpus has its own reports, ledger and cache. Nothing it does can touch build/llm or the published results.
HARD_LIVE_DIR = REPO / "build" / "llm_hard"
HARD_FAKE_DIR = HARD_LIVE_DIR / "fake"
PROTECTED_RESULTS = REPO / "results" / "benchmark_2026-11-06"
SET_FILE = "set.json"
# Programs of corpus/ with a state machine, explicit or implied by a timer chain. See docs/HARD_CORPUS.md.
ECC_PERSISTENT_PROGRAMS = ("06_star_delta", "13_case_sequencer", "14_batch_filling", "20_pump_station_supervisor")
TUNING, HELDOUT = "stimulus.json", "heldout_stimulus.json"
MORE_HELDOUT = "heldout_stimulus_*.json"  # Every one is scored and none is shown. Each stimulus file has one scan period.
# What each set is, in the words a report has to use. See docs/HARD_CORPUS.md.
SET_LABELS = {
    "siemens_scl": "TIA-style, never compiled, judged by matiec readings",
    "rockwell_st": "Logix-flavoured dialect with invented instructions",
    "public_st": "public programs; p03 and p04 pass the translator, so they say nothing about model against baseline",
    "stress": "self-authored, written by this project's AI tooling",
    "unsupported_st": "self-authored plain ST outside the translator's scope",
}
PASSES_BASELINE = ("p03_alpha_beta_filter", "p04_debounce_bool")
READING_WORDING = (
    "The model produced an FB equal to matiec's run of the reference on these stimuli, using the dialect's stated semantics, where the current translator's parser stops. "
    "{fell} of these programs fall to a small syntax front-end, and the others need ordinary compiler work (flattening and inlining). "
    "This does not show the model can do what deterministic code cannot, that it knows vendor semantics, or that the FB matches a real S7 or Logix controller."
)
FAKE_BANNER = "FAKE CLIENT. These are scripted responses and invented token counts, NOT results from any model."
EXIT_BUDGET = 3
EXIT_API = 4
EXIT_NOT_CHECKED = 5


@dataclass(frozen=True)
class Case:
    name: str
    source: str  # What the model and the baseline see.
    tuning_path: Path
    heldout_path: Path
    oracle: str | None = None  # What matiec runs. None means source. A dialect program has a hand-written reference.st.
    set_name: str = ""
    dialect: str | None = None
    extra_heldout: tuple[Path, ...] = ()  # Scored like heldout_path, and a run must pass all of them.
    max_tokens: int | None = None  # A recorded setting from set.json, used unless --max-tokens is given. None: the default.

    def has_case(self) -> bool:
        return re.search(r"\bCASE\b", self.source, flags=re.IGNORECASE) is not None

    @property
    def oracle_source(self) -> str:
        return self.source if self.oracle is None else self.oracle

    @property
    def heldout_paths(self) -> tuple[Path, ...]:
        return (self.heldout_path, *self.extra_heldout)


def load_set(directory: Path, names: Sequence[str] | None = None) -> list[Case]:
    """One set of corpus_hard/. Its set.json names the dialect and which file is which."""
    settings = json.loads((directory / SET_FILE).read_text(encoding="utf-8"))
    cases = []
    for program in sorted(path.parent for path in directory.glob(f"*/{settings['source_file']}")):
        if names is not None and program.name not in names:
            continue
        source = (program / settings["source_file"]).read_text(encoding="utf-8")
        oracle = None
        if settings["oracle_file"] != settings["source_file"]:
            oracle = (program / settings["oracle_file"]).read_text(encoding="utf-8")
        cases.append(Case(
            program.name, source, program / TUNING, program / HELDOUT, oracle, directory.name, settings["dialect"],
            tuple(sorted(program.glob(MORE_HELDOUT))), settings.get("max_tokens"),
        ))
    return cases


def load_corpus_dirs(directories: Sequence[Path], names: Sequence[str]) -> list[Case]:
    wanted = None if names == ["all"] else set(names)
    cases = [case for directory in directories for case in load_set(directory, wanted)]
    if wanted is not None and wanted - {case.name for case in cases}:
        raise SystemExit(f"unknown programs: {sorted(wanted - {case.name for case in cases})}")
    return cases


def load_cases(corpus: Path, names: Sequence[str]) -> list[Case]:
    directories = sorted(path.parent for path in corpus.glob("*/program.st"))
    if names != ["all"]:
        known = {path.name: path for path in directories}
        unknown = [name for name in names if name not in known]
        if unknown:
            raise SystemExit(f"unknown programs: {unknown}")
        directories = [known[name] for name in names]
    return [
        Case(d.name, (d / "program.st").read_text(encoding="utf-8"), d / TUNING, d / HELDOUT)
        for d in directories
    ]


def parse_models(specs: Sequence[str], default_repeats: int) -> list[tuple[str, int]]:
    """Each --model entry is MODEL or MODEL:REPEATS."""
    plan = []
    for spec in specs:
        model, _, repeats = spec.partition(":")
        if model not in ALLOWED_MODELS:
            raise SystemExit(f"--model must be one of {ALLOWED_MODELS}, got {model!r}")
        plan.append((model, int(repeats) if repeats else default_repeats))
    return plan


# ---- Dry run ----


def profile_of(case: Case, form: str | None) -> prompts.PromptProfile:
    return prompts.PromptProfile(case.dialect, form)


def tokens_for(case: Case, requested: int | None) -> int:
    """--max-tokens if given, else the program's recorded setting, else the default."""
    if requested is not None:
        return requested
    return case.max_tokens if case.max_tokens is not None else DEFAULT_MAX_TOKENS


def planned_rows(
    cases: list[Case], modes: Sequence[str], models: list[tuple[str, int]], args: argparse.Namespace, form: str | None = None
) -> list[dict[str, Any]]:
    rows = []
    for model, repeats in models:
        for case in cases:
            config = LlmConfig(model, args.effort, tokens_for(case, args.max_tokens), not args.no_fallbacks)
            profile = profile_of(case, form)
            system = prompts.system_prompt(profile)
            first = input_token_bound(system, prompts.generate_prompt(case.source, profile))
            # A repair prompt also repeats the previous reply, at most max_tokens long, and the failure.
            repair = input_token_bound(system, prompts.repair_prompt(case.source, "", "")) + config.max_tokens + FAILURE_LIMIT
            for mode in modes:
                worst = worst_case_usd(config, first) + (MODE_ATTEMPTS[mode] - 1) * worst_case_usd(config, repair)
                rows.append({
                    "model": model,
                    "program": case.name,
                    "mode": mode,
                    "repeats": repeats,
                    "max_requests": MODE_ATTEMPTS[mode] * repeats,
                    "worst_case_usd": worst * repeats,
                    "first_request_usd": worst_case_usd(config, first) * repeats,
                    "max_tokens": config.max_tokens,
                })
    return rows


def dry_run(
    cases: list[Case], modes: Sequence[str], models: list[tuple[str, int]], args: argparse.Namespace, form: str | None = None, per_model: bool = False
) -> int:
    rows = planned_rows(cases, modes, models, args, form)
    print(f"DRY RUN: nothing is sent, and no key is read. Prices as cached on {PRICES_AS_OF}.")
    default_tokens = args.max_tokens if args.max_tokens is not None else DEFAULT_MAX_TOKENS
    print(f"effort={args.effort} max_tokens={default_tokens} server_side_fallback={not args.no_fallbacks}")
    for row in rows:
        if row["max_tokens"] != default_tokens:
            print(f"{row['program']} has its own recorded max_tokens={row['max_tokens']}, from its set.json.")
            break
    for name in sorted({case.set_name for case in cases if case.set_name}):
        print(f"{name}: {SET_LABELS.get(name, '')}")
    print(f"{'model':20} {'program':30} {'mode':11} {'repeats':>7} {'max requests':>12} {'worst case USD':>15}")
    for row in rows:
        print(
            f"{row['model']:20} {row['program']:30} {row['mode']:11} {row['repeats']:7d} "
            f"{row['max_requests']:12d} {row['worst_case_usd']:15.4f}"
        )
    requests = sum(row["max_requests"] for row in rows)
    worst = sum(row["worst_case_usd"] for row in rows)
    if len(set(modes)) > 1:
        # llm_only's one request is identical to llm_repair's first attempt, so the cache serves it.
        shared = [row for row in rows if row["mode"] == "llm_only"]
        requests -= sum(row["max_requests"] for row in shared)
        worst -= sum(row["first_request_usd"] for row in shared)
        print("The rows above count each mode alone. llm_only and llm_repair share their first attempt, so the total is lower.")
    print(f"TOTAL: at most {requests} requests, worst case ${worst:.2f}.")
    if per_model and len(models) > 1:
        for model, _ in models:
            mine = [row for row in rows if row["model"] == model]
            own_worst = sum(row["worst_case_usd"] for row in mine)
            if len(set(modes)) > 1:
                own_worst -= sum(row["first_request_usd"] for row in mine if row["mode"] == "llm_only")
            print(f"  of which {model}: worst case ${own_worst:.2f}")
    print("Worst case: every request uses all of max_tokens, one token per input byte, input billed at the")
    if args.no_fallbacks:
        print("cache-write rate, and every repair loop runs out. Server-side fallback is off, so no second model")
        print("runs. Expect far less. The disk cache is not taken into account. Real cost comes from response.usage.")
    else:
        print("cache-write rate, every repair loop runs out, and every request also runs a fallback model at its")
        print("full length. Expect far less. The disk cache is not taken into account. Real cost comes from response.usage.")
    return 0


# ---- Scoring ----


NOT_ASSESSED: dict[str, Any] = {"ecc_persistent": None, "ecc_verdict": None, "control_states": None, "ecc_persistent_failures": [], "ecc_needs_reading": []}


def run_baseline(case: Case, references: dict[str, dict[str, Any]], kind: str) -> dict[str, Any]:
    candidate = fbt.write_fbt(translate_source(case.source))
    tuning = forte_eval.evaluate(candidate, case.tuning_path, references["tuning"])
    heldout = forte_eval.evaluate(candidate, case.heldout_path, references["heldout"])
    return {
        "client": kind,  # The translator's results are real, but they sit in this run's report.
        "program": case.name,
        "mode": "baseline",
        "model": "deterministic-translator",
        "repeat": 0,
        "tuning_equal": tuning.equal,
        "heldout_equal": heldout.equal,
        "passed": tuning.equal and heldout.equal,
        "attempts": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "new_spend_usd": 0.0,
        "source_has_case": case.has_case(),
        "failure_category": None if tuning.equal and heldout.equal else "baseline_failed",
        **ecc_structure(candidate),
    }


def held_out_outcomes(candidate: str, case: Case, references: dict[str, Any]) -> dict[str, forte_eval.Outcome]:
    """The candidate on every held-out stimulus, by file name. Runs only after a migration, and nothing here goes back to a model."""
    return {path.name: forte_eval.evaluate(candidate, path, trace) for path, trace in zip(case.heldout_paths, references["heldout_all"])}


def load_references(case: Case, container: reference_run.Container) -> dict[str, Any]:
    def run(path: Path) -> dict[str, Any]:
        return reference_run.run_reference(case.oracle_source, json.loads(path.read_text(encoding="utf-8")), container)

    held = [run(path) for path in case.heldout_paths]
    return {"tuning": run(case.tuning_path), "heldout": held[0], "heldout_all": held}


def frontend_tier(case: Case, references: dict[str, Any]) -> dict[str, Any]:
    """The translator again, behind the small syntax front-end of st2fb/vendor_frontend.py. Never given the reference."""
    try:
        translated = translate_source(to_plain_st(case.source, case.dialect))
    except ValueError as exc:  # FrontendError, STParseError and TranslateError are all ValueError.
        return {"frontend_status": "rejected", "frontend_reason": str(exc)}
    candidate = fbt.write_fbt(translated)
    outcomes = {TUNING: forte_eval.evaluate(candidate, case.tuning_path, references["tuning"]), **held_out_outcomes(candidate, case, references)}
    passed = all(outcome.equal for outcome in outcomes.values())
    return {
        "frontend_status": "passed" if passed else "failed",
        "frontend_reason": "" if passed else ", ".join(f"{name}: {outcome.status}" for name, outcome in outcomes.items() if not outcome.equal),
    }


def run_baseline_hard(case: Case, references: dict[str, Any], kind: str) -> dict[str, Any]:
    """Both deterministic tiers on what the model sees. A rejection is the expected result on most of this corpus, and is not a crash."""
    row = {
        "client": kind,
        "program": case.name,
        "set": case.set_name,
        "dialect": case.dialect,
        "mode": "baseline",
        "model": "deterministic-translator",
        "repeat": 0,
        "attempts": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "new_spend_usd": 0.0,
        "source_has_case": case.has_case(),
        **frontend_tier(case, references),
    }
    try:
        translated = translate_source(case.source)
    except ValueError as exc:  # STParseError and TranslateError are both ValueError.
        return {
            **row,
            "baseline_status": "rejected",
            "baseline_reason": str(exc),
            "tuning_equal": None,
            "heldout_equal": None,
            "passed": False,
            "failure_category": "baseline_rejected",
            "ecc_states": None,
            "working_states": None,
            "algorithms": None,
            "restructured": None,
            **NOT_ASSESSED,
        }
    candidate = fbt.write_fbt(translated)
    tuning = forte_eval.evaluate(candidate, case.tuning_path, references["tuning"])
    held = held_out_outcomes(candidate, case, references)
    heldout_equal = all(outcome.equal for outcome in held.values())
    passed = tuning.equal and heldout_equal
    return {
        **row,
        "baseline_status": "passed" if passed else "failed",
        "baseline_reason": "",
        "tuning_equal": tuning.equal,
        "heldout_equal": heldout_equal,
        "passed": passed,
        "failure_category": None if passed else "baseline_failed",
        **ecc_structure(candidate),
        **ecc_persistence(candidate),
    }


def score(
    case: Case,
    mode: str,
    config: LlmConfig,
    repeat: int,
    kind: str,
    migration: MigrationResult,
    references: dict[str, dict[str, Any]],
    out_dir: Path,
    hard: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Take the final score. Runs only after the migration, and nothing here goes back to the model."""
    heldout_equal = None
    heldout_files: dict[str, str] = {}
    category = migration.failure_category
    stopped_early = migration.stop_run is not None
    if migration.candidate is not None and migration.tuning_status in ("equal", "different") and not stopped_early:
        if case.extra_heldout:
            outcomes = held_out_outcomes(migration.candidate, case, references)
        else:
            outcomes = {case.heldout_path.name: forte_eval.evaluate(migration.candidate, case.heldout_path, references["heldout"])}
        heldout_files = {name: outcome.status for name, outcome in outcomes.items()}
        heldout_equal = all(outcome.equal for outcome in outcomes.values())
        failed = next((outcome for outcome in outcomes.values() if not outcome.equal), None)
        if migration.tuning_equal and failed is not None:
            # Fits the stimulus it was tuned on, and is wrong in general. This is the overfit case.
            category = "heldout_different" if failed.status == "different" else CATEGORY_OF_STATUS[failed.status]
    records = [attempt.to_dict() for attempt in migration.attempts]
    usage = [entry for record in records for entry in record["usage"]]
    candidate_path = None
    if migration.candidate is not None:
        path = out_dir / "candidates" / config.model / case.name / f"{mode}_r{repeat}.fbt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(migration.candidate, encoding="utf-8")
        candidate_path = str(path)
    extra: dict[str, Any] = {}
    if hard is not None:
        extra = {**hard, "heldout_files": heldout_files, "max_tokens": config.max_tokens, **(ecc_persistence(migration.candidate) if migration.candidate else NOT_ASSESSED)}
    return {
        **extra,
        "client": kind,
        "program": case.name,
        "mode": mode,
        "model": config.model,
        "effort": config.effort,
        "repeat": repeat,
        "tuning_equal": migration.tuning_equal,
        "heldout_equal": heldout_equal,
        "passed": migration.tuning_equal and heldout_equal is True,
        "attempts": len(records),
        "input_tokens": sum(e["input_tokens"] + e["cache_creation_input_tokens"] + e["cache_read_input_tokens"] for e in usage),
        "output_tokens": sum(e["output_tokens"] for e in usage),
        "cost_usd": sum(record["cost_usd"] for record in records),
        "new_spend_usd": sum(record["new_spend_usd"] for record in records),
        "cached_calls": sum(record["cached"] for record in records),
        "served_by": sorted({record["served_by"] for record in records if record["served_by"]}),
        "fell_back": any(record["fell_back"] for record in records),
        "source_has_case": case.has_case(),
        "failure_category": category,
        "tuning_first_divergence": migration.tuning_first_divergence,
        "candidate_path": candidate_path,
        "attempt_log": records,
        **(ecc_structure(migration.candidate) if migration.candidate else {"ecc_states": None, "working_states": None, "algorithms": None, "restructured": None}),
    }


def not_run_row(case: Case, mode: str, config: LlmConfig, repeat: int, kind: str, hard: dict[str, Any] | None = None) -> dict[str, Any]:
    extra = {**hard, **NOT_ASSESSED} if hard is not None else {}
    return {
        **extra,
        "client": kind,
        "program": case.name,
        "mode": mode,
        "model": config.model,
        "effort": config.effort,
        "repeat": repeat,
        "tuning_equal": False,
        "heldout_equal": None,
        "passed": False,
        "attempts": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "new_spend_usd": 0.0,
        "source_has_case": case.has_case(),
        "failure_category": "not_run",
        "ecc_states": None,
        "working_states": None,
        "algorithms": None,
        "restructured": None,
    }


def aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["model"], row["mode"]), []).append(row)
    summary = []
    for (model, mode), group in sorted(groups.items()):
        ran = [row for row in group if row["mode"] == "baseline" or row["attempts"] > 0]
        passed = [row for row in ran if row["passed"]]
        cost = sum(row["cost_usd"] for row in group)
        summary.append({
            "model": model,
            "mode": mode,
            "runs": len(ran),
            "not_run": len(group) - len(ran),
            "tuning_equal": sum(bool(row["tuning_equal"]) for row in ran),
            "heldout_equal": sum(bool(row["heldout_equal"]) for row in ran),
            "passed": len(passed),
            "restructured_and_passed": sum(bool(row.get("restructured")) for row in passed),
            "cost_usd": cost,
            "new_spend_usd": sum(row["new_spend_usd"] for row in group),
            "cost_per_pass_usd": cost / len(passed) if passed else None,
            "fell_back": sum(bool(row.get("fell_back")) for row in group),
            "failures": dict(Counter(row["failure_category"] for row in group if row["failure_category"])),
        })
    return summary


def render_markdown(document: dict[str, Any]) -> str:
    kind = document["client"]
    lines = ["# LLM benchmark", ""]
    if kind == FAKE:
        lines += [f"**{FAKE_BANNER}**", ""]
    lines += [
        f"`client`: `{kind}`. Prices as cached on {document['prices_as_of']}; check real cost against the Console.",
        "",
    ]
    if document.get("stopped"):
        lines += [f"**The run stopped early: {document['stopped']}**", ""]
    lines += [
        "A run passes only if its final candidate equals matiec on the tuning stimulus and on the held-out stimulus,",
        "which the model never saw. `restructured` is about structure only: it means at least two EC states with",
        "actions, so `no` on a correct run is a one-state wrapper, which is what a program with no state machine should get.",
        "",
        "In the same repeat, `llm_only` and `llm_repair` share their first attempt, because the prompt is identical and the",
        "cache serves it. So the two modes are paired samples and not independent ones. `Cost USD` is what each mode would",
        "have cost alone, so it counts that request in both. `Spent now USD` is what this run actually paid.",
        "",
        "## Aggregate",
        "",
        "| Model | Mode | Runs | Not run | Tuning equal | Held-out equal | Passed | Passed and restructured | Cost USD | Spent now USD | Cost per pass USD | Fell back | Failures |",
        "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|",
    ]
    for row in document["aggregate"]:
        per_pass = f"{row['cost_per_pass_usd']:.4f}" if row["cost_per_pass_usd"] is not None else "n/a"
        lines.append(
            f"| {row['model']} | {row['mode']} | {row['runs']} | {row['not_run']} | {row['tuning_equal']} | {row['heldout_equal']} "
            f"| {row['passed']} | {row['restructured_and_passed']} | {row['cost_usd']:.4f} | {row['new_spend_usd']:.4f} | {per_pass} "
            f"| {row['fell_back']} | {row['failures'] or ''} |"
        )
    lines += [
        "",
        "## Per program, mode and repeat",
        "",
        "| Program | Mode | Model | Repeat | Tuning equal | Held-out equal | Passed | Attempts | Input tokens | Output tokens | Cost USD | ECC states | Working states | Restructured | Has CASE | Failure |",
        "|---|---|---|--:|---|---|---|--:|--:|--:|--:|--:|--:|---|---|---|",
    ]
    for row in document["results"]:
        yes_no = lambda value: {True: "yes", False: "no", None: "n/a"}[value]  # noqa: E731
        lines.append(
            f"| {row['program']} | {row['mode']} | {row['model']} | {row['repeat']} | {yes_no(row['tuning_equal'])} "
            f"| {yes_no(row['heldout_equal'])} | {yes_no(row['passed'])} | {row['attempts']} | {row['input_tokens']} "
            f"| {row['output_tokens']} | {row['cost_usd']:.4f} | {row['ecc_states'] if row['ecc_states'] is not None else 'n/a'} "
            f"| {row['working_states'] if row['working_states'] is not None else 'n/a'} | {yes_no(row['restructured'])} "
            f"| {yes_no(row['source_has_case'])} | {row['failure_category'] or ''} |"
        )
    return "\n".join(lines) + "\n"


def baseline_summary(rows: list[dict[str, Any]], status: str = "baseline_status") -> dict[str, list[str]]:
    summary: dict[str, list[str]] = {"rejected": [], "passed": [], "failed": []}
    for row in rows:
        if row["mode"] == "baseline":
            summary[row[status]].append(row["program"])
    return summary


def aggregate_hard(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """aggregate(), plus what the hard corpus is for: a model's passes against both deterministic tiers, and strict ECC passes."""
    translator = baseline_summary(rows)
    frontend = baseline_summary(rows, "frontend_status")
    summary = aggregate(rows)
    for entry in summary:
        passed = [r for r in rows if (r["model"], r["mode"]) == (entry["model"], entry["mode"]) and r["passed"]]
        entry["passed_where_translator_rejected"] = sum(row["program"] in translator["rejected"] for row in passed)
        entry["passed_where_frontend_did_not_pass"] = sum(row["program"] not in frontend["passed"] for row in passed)
        entry["passed_and_persistent"] = sum(row.get("ecc_persistent") is True for row in passed)
        entry["passed_needs_reading"] = sum(row.get("ecc_verdict") == "needs_reading" for row in passed)
    return summary


def render_hard_markdown(document: dict[str, Any]) -> str:
    kind = document["client"]
    lines = ["# LLM benchmark, hard corpus", ""]
    if kind == FAKE:
        lines += [f"**{FAKE_BANNER}**", ""]
    lines += [
        f"`client`: `{kind}`. Sets: {', '.join(document['sets']) or 'corpus'}. Requested form: {document['form'] or 'default'}. "
        f"Prices as cached on {document['prices_as_of']}; check real cost against the Console.",
        "",
    ]
    if document.get("stopped"):
        lines += [f"**The run stopped early: {document['stopped']}**", ""]
    lines += [
        "A run passes only if its final candidate equals matiec on the tuning stimulus and on the held-out stimulus. Structure never decides a pass.",
        "`Persistent` is the strict metric: control position is held by ECC state across REQ events. See `st2fb/llm/ecc_metric.py`. `Restructured` only counts states with actions.",
        "",
        "These programs were written by this project, except public_st. SCL and Logix sources were never compiled by TIA Portal or Studio 5000, and the oracle for them is a hand-written",
        "translation, so an error in the pairing would count against the model. Inspect a failure before assuming that the model is wrong. See `docs/HARD_CORPUS.md`.",
        "",
    ]
    for name in document["sets"]:
        if name in SET_LABELS:
            lines.append(f"- `{name}`: {SET_LABELS[name]}.")
    lines += [
        "",
        "## Baseline tiers",
        "",
        "Two deterministic comparators run on every program. `translator` is the current translator on what the model sees. `frontend+translator` puts `st2fb/vendor_frontend.py`, a small syntax rewrite",
        "that never sees the reference, in front of it. `rejected` under `translator` means only that this parser or scope stopped, and it is the expected result here. A model's pass is compared with both tiers.",
        "",
        "| Tier | Status | Programs | Which |",
        "|---|---|--:|---|",
    ]
    for tier, summary in (("translator", document["baseline"]), ("frontend+translator", document["baseline_frontend"])):
        for status, programs in summary.items():
            lines.append(f"| {tier} | {status} | {len(programs)} | {', '.join(programs)} |")
    rejected = document["baseline"]["rejected"]
    fell = sum(program in document["baseline_frontend"]["passed"] for program in rejected)
    wording = READING_WORDING.format(fell=f"{fell} of {len(rejected)}")
    lines += [
        "",
        f"How to read a model's pass where the translator rejected the source: {wording}",
        "",
        "## Aggregate",
        "",
        "| Model | Mode | Runs | Not run | Tuning equal | Held-out equal | Passed | Passed where translator rejected | Passed where frontend+translator did not pass | Passed and persistent | Passed, needs reading | Passed and restructured | Cost USD | Spent now USD | Cost per pass USD | Fell back | Failures |",
        "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|",
    ]
    for row in document["aggregate"]:
        per_pass = f"{row['cost_per_pass_usd']:.4f}" if row["cost_per_pass_usd"] is not None else "n/a"
        lines.append(
            f"| {row['model']} | {row['mode']} | {row['runs']} | {row['not_run']} | {row['tuning_equal']} | {row['heldout_equal']} | {row['passed']} "
            f"| {row['passed_where_translator_rejected']} | {row['passed_where_frontend_did_not_pass']} | {row['passed_and_persistent']} | {row['passed_needs_reading']} | {row['restructured_and_passed']} | {row['cost_usd']:.4f} | {row['new_spend_usd']:.4f} "
            f"| {per_pass} | {row['fell_back']} | {row['failures'] or ''} |"
        )
    lines += [
        "",
        "## Per program, mode and repeat",
        "",
        "| Set | Program | Translator | Frontend+translator | Mode | Model | Repeat | Tuning equal | Held-out equal | Passed | Attempts | Input tokens | Output tokens | Cost USD | ECC states | Working states | Restructured | Persistent | Control states | Has CASE | Failure |",
        "|---|---|---|---|---|---|--:|---|---|---|--:|--:|--:|--:|--:|--:|---|---|--:|---|---|",
    ]
    yes_no = {True: "yes", False: "no", None: "n/a"}
    baseline = {program: status for status, programs in document["baseline"].items() for program in programs}
    frontend = {program: status for status, programs in document["baseline_frontend"].items() for program in programs}
    persistent = {"persistent": "yes", "not_persistent": "no", "needs_reading": "needs reading", None: "n/a"}
    for row in document["results"]:
        number = lambda value: value if value is not None else "n/a"  # noqa: E731
        lines.append(
            f"| {row.get('set', '')} | {row['program']} | {baseline.get(row['program'], 'n/a')} | {frontend.get(row['program'], 'n/a')} | {row['mode']} | {row['model']} | {row['repeat']} | {yes_no[row['tuning_equal']]} "
            f"| {yes_no[row['heldout_equal']]} | {yes_no[row['passed']]} | {row['attempts']} | {row['input_tokens']} | {row['output_tokens']} | {row['cost_usd']:.4f} "
            f"| {number(row['ecc_states'])} | {number(row['working_states'])} | {yes_no[row['restructured']]} | {persistent.get(row.get('ecc_verdict'), 'n/a')} | {number(row.get('control_states'))} "
            f"| {yes_no[row['source_has_case']]} | {row['failure_category'] or ''} |"
        )
    return "\n".join(lines) + "\n"


def write_reports(
    rows: list[dict[str, Any]], kind: str, out_dir: Path, stopped: str | None, hard: dict[str, Any] | None = None
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "client": kind,
        "prices_as_of": PRICES_AS_OF,
        "stopped": stopped,
        "aggregate": aggregate_hard(rows) if hard is not None else aggregate(rows),
        "results": rows,
    }
    if hard is not None:
        document.update(hard)
        document["baseline"] = baseline_summary(rows)
        document["baseline_frontend"] = baseline_summary(rows, "frontend_status")
    if kind == FAKE:
        document["warning"] = FAKE_BANNER
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "benchmark.json").write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    render = render_hard_markdown if hard is not None else render_markdown
    (out_dir / "benchmark.md").write_text(render(document), encoding="utf-8")
    return document


# ---- Running ----


def echo_translator_client() -> FakeClient:
    """The default fake: answers each request with the deterministic translation of the source in it."""

    def reply(request: LlmRequest) -> FakeReply:
        match = re.search(r"```\n(.*?END_FUNCTION_BLOCK)", request.user, flags=re.DOTALL | re.IGNORECASE)
        if match is None:
            return FakeReply(text="no source found in the prompt")
        try:
            return FakeReply(text=fbt.write_fbt(translate_source(match.group(1))))
        except ValueError as exc:  # The hard corpus is meant to be out of the translator's reach.
            return FakeReply(text=f"the fake client cannot translate this source: {exc}")

    return FakeClient(reply)


def make_live_client(env_file: Path) -> ModelClient:
    """Reads the key and imports the SDK, and so is only called for an explicit --live."""
    from .live_client import AnthropicClient

    return AnthropicClient(load_api_key(env_file))


def run_benchmark(
    cases: list[Case],
    modes: Sequence[str],
    models: list[tuple[str, int]],
    client: ModelClient,
    budget_usd: float | None,
    out_dir: Path,
    effort: str = DEFAULT_EFFORT,
    max_tokens: int | None = None,
    fallbacks: bool = True,
    sleep: Callable[[float], None] | None = None,
    hard: dict[str, Any] | None = None,
    store_dir: Path | None = None,
) -> tuple[dict[str, Any], int]:
    """hard: {"sets": [...], "form": ...} selects the hard-corpus rows and report. None is the first benchmark's format.

    store_dir: where the ledger and the cache live, default out_dir. Reports of several hard sets share one, so that
    --budget-usd stays one cumulative cap across them.
    """
    kind = client.kind
    store_dir = store_dir or out_dir
    if kind == LIVE and hard is not None:
        manifest.require_passed()  # A live run spends money, so this holds however it was started.
    for directory in (out_dir, store_dir):
        resolved = directory.resolve()
        if kind == FAKE and resolved in (LIVE_DIR.resolve(), HARD_LIVE_DIR.resolve()):
            raise ValueError("fake results must not be written to the live results directory")
        if resolved == PROTECTED_RESULTS.resolve() or PROTECTED_RESULTS.resolve() in resolved.parents:
            raise ValueError(f"{PROTECTED_RESULTS} backs published numbers and is never written to")
    ledger = Ledger(store_dir / "ledger.jsonl", kind)
    cache = ResponseCache(store_dir / "cache", kind)
    extra = {"sleep": sleep} if sleep else {}
    gateway = Gateway(client, ledger, cache, budget_usd, **extra)

    rows: list[dict[str, Any]] = []
    stopped: str | None = None
    exit_code = 0
    reference_run.ensure_image()
    with reference_run.Container() as container:
        references = {}
        for case in cases:
            references[case.name] = load_references(case, container)
            if hard is None:
                rows.append(run_baseline(case, references[case.name], kind))
            else:
                rows.append(run_baseline_hard(case, references[case.name], kind))

        for model, repeats in models:
            for case in cases:
                config = LlmConfig(model, effort, tokens_for(case, max_tokens), fallbacks)
                program = ProgramInput(case.name, case.source, case.tuning_path, references[case.name]["tuning"])
                profile = profile_of(case, hard["form"] if hard else None)
                row_extra = {"set": case.set_name, "dialect": case.dialect} if hard is not None else None
                for mode in modes:
                    for repeat in range(repeats):
                        if stopped:
                            rows.append(not_run_row(case, mode, config, repeat, kind, row_extra))
                            continue
                        migration = migrate(program, mode, config, gateway, repeat, profile)
                        if migration.stop_run:
                            stopped = migration.stop_run
                            exit_code = EXIT_BUDGET if migration.failure_category == "budget_stop" else EXIT_API
                            print(f"benchmark: stopping, {stopped}", file=sys.stderr)
                        rows.append(score(case, mode, config, repeat, kind, migration, references[case.name], out_dir, row_extra))
                        forte_eval.prune_cache()
                        print(
                            f"{case.name} {mode} {model} r{repeat}: passed={rows[-1]['passed']} "
                            f"attempts={rows[-1]['attempts']} category={rows[-1]['failure_category']}",
                            flush=True,
                        )
                        # After every run, so that an interrupted benchmark still has a report.
                        write_reports(rows, kind, out_dir, stopped, hard)
    return write_reports(rows, kind, out_dir, stopped, hard), exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark LLM migration on real FORTE against matiec.")
    parser.add_argument("--programs", nargs="+", default=["all"], help="program names, or all")
    parser.add_argument("--modes", nargs="+", default=list(MODE_ATTEMPTS), choices=list(MODE_ATTEMPTS))
    parser.add_argument("--repeats", type=int, default=1, help="repeats per program, as independent samples")
    parser.add_argument("--model", nargs="+", default=[DEFAULT_MODEL], help="MODEL or MODEL:REPEATS, one or more")
    parser.add_argument("--effort", default=DEFAULT_EFFORT)
    parser.add_argument("--max-tokens", type=int, help=f"overrides a program's recorded setting. Default: that setting, or {DEFAULT_MAX_TOKENS}")
    parser.add_argument("--no-fallbacks", action="store_true", help="do not opt in to server-side fallback")
    parser.add_argument("--budget-usd", type=float, help="total spend allowed by the ledger; required with --live")
    parser.add_argument("--live", action="store_true", help="make real API calls, which cost money")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and the worst-case cost, and call nothing")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, help="used only with --live")
    parser.add_argument("--corpus", type=Path, default=REPO / "corpus")
    parser.add_argument("--corpus-dir", type=Path, nargs="+", help="one or more corpus_hard/<set> directories, each with a set.json")
    parser.add_argument("--form", choices=list(prompts.FORMS), help=f"ask for this ECC form. With no --programs and no --corpus-dir: {' '.join(ECC_PERSISTENT_PROGRAMS)}")
    parser.add_argument("--out-dir", type=Path, help="default build/llm for --live, build/llm/fake otherwise")
    args = parser.parse_args(argv)

    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    try:
        LlmConfig(DEFAULT_MODEL, args.effort, args.max_tokens if args.max_tokens is not None else DEFAULT_MAX_TOKENS)
    except ValueError as exc:
        parser.error(str(exc))
    hard = None
    if args.corpus_dir or args.form:
        hard = {"sets": [directory.name for directory in args.corpus_dir or []], "form": args.form}
    if args.corpus_dir:
        cases = load_corpus_dirs(args.corpus_dir, args.programs)
    elif args.form and args.programs == ["all"]:
        cases = load_cases(args.corpus, list(ECC_PERSISTENT_PROGRAMS))
    else:
        cases = load_cases(args.corpus, args.programs)
    models = parse_models(args.model, args.repeats)
    label = "+".join(hard["sets"] + ([hard["form"]] if hard["form"] else [])) if hard else ""

    if args.dry_run:
        return dry_run(cases, args.modes, models, args, args.form, hard is not None)

    if hard:
        try:
            manifest.require_passed()
        except manifest.NotChecked as exc:
            print(f"benchmark: {exc}", file=sys.stderr)
            return EXIT_NOT_CHECKED

    if args.live:
        if args.budget_usd is None or args.budget_usd <= 0:
            parser.error("--live needs a positive --budget-usd")
        try:
            client = make_live_client(args.env_file)
        except ApiKeyError as exc:
            print(f"benchmark: {exc}", file=sys.stderr)
            return 2
        except ImportError:
            print("benchmark: --live needs the SDK: pip install -r requirements-llm.txt in .venv", file=sys.stderr)
            return 2
        store_dir = args.out_dir or (HARD_LIVE_DIR if hard else LIVE_DIR)
    else:
        client = echo_translator_client()
        store_dir = args.out_dir or (HARD_FAKE_DIR if hard else FAKE_DIR)
        print(f"benchmark: {FAKE_BANNER}", file=sys.stderr)
    out_dir = args.out_dir or (store_dir / "reports" / label if hard else store_dir)

    document, code = run_benchmark(
        cases, args.modes, models, client, args.budget_usd, out_dir, args.effort, args.max_tokens, not args.no_fallbacks,
        hard=hard, store_dir=store_dir,
    )
    print(f"wrote {out_dir / 'benchmark.json'} and {out_dir / 'benchmark.md'}, client={document['client']}")
    return code


if __name__ == "__main__":
    sys.exit(main())
