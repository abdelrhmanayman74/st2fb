"""Benchmark LLM migration against the deterministic translator on identical inputs.

    python3 -m st2fb.llm.benchmark --dry-run --programs all --model claude-sonnet-5-5:3 claude-opus-5-5:1
    python3 -m st2fb.llm.benchmark --programs 00_latch                 # fake client, no network, no key
    python3 -m st2fb.llm.benchmark --live --budget-usd 1 --programs 00_latch --modes llm_only

Without --live, the only client that can be constructed is the fake one, which echoes the deterministic
translator's output, and results go to build/llm/fake/. Reports say which client made them.

The score is taken on heldout_stimulus.json after the migration has finished. A run passes only if the
final candidate equals matiec on both the tuning and the held-out stimulus.
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
from . import prompts
from .budget import Ledger
from .cache import ResponseCache
from .client import FAKE, FakeClient, FakeReply, LlmRequest, ModelClient
from .config import ALLOWED_MODELS, DEFAULT_EFFORT, DEFAULT_MAX_TOKENS, DEFAULT_MODEL, PRICES_AS_OF, LlmConfig, input_token_bound, worst_case_usd
from .engine import FAILURE_LIMIT, MODE_ATTEMPTS, CATEGORY_OF_STATUS, MigrationResult, ProgramInput, ecc_structure, migrate
from .gateway import Gateway
from .keys import DEFAULT_ENV_FILE, ApiKeyError, load_api_key

REPO = Path(__file__).resolve().parent.parent.parent
LIVE_DIR = REPO / "build" / "llm"
FAKE_DIR = LIVE_DIR / "fake"
TUNING, HELDOUT = "stimulus.json", "heldout_stimulus.json"
FAKE_BANNER = "FAKE CLIENT. These are scripted responses and invented token counts, NOT results from any model."
EXIT_BUDGET = 3
EXIT_API = 4


@dataclass(frozen=True)
class Case:
    name: str
    source: str
    tuning_path: Path
    heldout_path: Path

    def has_case(self) -> bool:
        return re.search(r"\bCASE\b", self.source, flags=re.IGNORECASE) is not None


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


def planned_rows(cases: list[Case], modes: Sequence[str], models: list[tuple[str, int]], args: argparse.Namespace) -> list[dict[str, Any]]:
    system = prompts.system_prompt()
    rows = []
    for model, repeats in models:
        config = LlmConfig(model, args.effort, args.max_tokens, not args.no_fallbacks)
        for case in cases:
            first = input_token_bound(system, prompts.generate_prompt(case.source))
            # A repair prompt also repeats the previous reply, at most max_tokens long, and the failure.
            repair = input_token_bound(system, prompts.repair_prompt(case.source, "", "")) + args.max_tokens + FAILURE_LIMIT
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
                })
    return rows


def dry_run(cases: list[Case], modes: Sequence[str], models: list[tuple[str, int]], args: argparse.Namespace) -> int:
    rows = planned_rows(cases, modes, models, args)
    print(f"DRY RUN: nothing is sent, and no key is read. Prices as cached on {PRICES_AS_OF}.")
    print(f"effort={args.effort} max_tokens={args.max_tokens} server_side_fallback={not args.no_fallbacks}")
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
    print("Worst case: every request uses all of max_tokens, one token per input byte, input billed at the")
    print("cache-write rate, every repair loop runs out, and every request also runs a fallback model at its")
    print("full length. Expect far less. The disk cache is not taken into account. Real cost comes from response.usage.")
    return 0


# ---- Scoring ----


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


def score(
    case: Case,
    mode: str,
    config: LlmConfig,
    repeat: int,
    kind: str,
    migration: MigrationResult,
    references: dict[str, dict[str, Any]],
    out_dir: Path,
) -> dict[str, Any]:
    """Take the final score. Runs only after the migration, and nothing here goes back to the model."""
    heldout_equal = None
    category = migration.failure_category
    stopped_early = migration.stop_run is not None
    if migration.candidate is not None and migration.tuning_status in ("equal", "different") and not stopped_early:
        heldout = forte_eval.evaluate(migration.candidate, case.heldout_path, references["heldout"])
        heldout_equal = heldout.equal
        if migration.tuning_equal and not heldout.equal:
            # Fits the stimulus it was tuned on, and is wrong in general. This is the overfit case.
            category = "heldout_different" if heldout.status == "different" else CATEGORY_OF_STATUS[heldout.status]
    records = [attempt.to_dict() for attempt in migration.attempts]
    usage = [entry for record in records for entry in record["usage"]]
    candidate_path = None
    if migration.candidate is not None:
        path = out_dir / "candidates" / config.model / case.name / f"{mode}_r{repeat}.fbt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(migration.candidate, encoding="utf-8")
        candidate_path = str(path)
    return {
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


def not_run_row(case: Case, mode: str, config: LlmConfig, repeat: int, kind: str) -> dict[str, Any]:
    return {
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


def write_reports(rows: list[dict[str, Any]], kind: str, out_dir: Path, stopped: str | None) -> dict[str, Any]:
    document: dict[str, Any] = {
        "client": kind,
        "prices_as_of": PRICES_AS_OF,
        "stopped": stopped,
        "aggregate": aggregate(rows),
        "results": rows,
    }
    if kind == FAKE:
        document["warning"] = FAKE_BANNER
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "benchmark.json").write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    (out_dir / "benchmark.md").write_text(render_markdown(document), encoding="utf-8")
    return document


# ---- Running ----


def echo_translator_client() -> FakeClient:
    """The default fake: answers each request with the deterministic translation of the source in it."""

    def reply(request: LlmRequest) -> FakeReply:
        match = re.search(r"```\n(.*?END_FUNCTION_BLOCK)", request.user, flags=re.DOTALL | re.IGNORECASE)
        if match is None:
            return FakeReply(text="no source found in the prompt")
        return FakeReply(text=fbt.write_fbt(translate_source(match.group(1))))

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
    max_tokens: int = DEFAULT_MAX_TOKENS,
    fallbacks: bool = True,
    sleep: Callable[[float], None] | None = None,
) -> tuple[dict[str, Any], int]:
    kind = client.kind
    if kind == FAKE and out_dir.resolve() == LIVE_DIR.resolve():
        raise ValueError("fake results must not be written to the live results directory")
    ledger = Ledger(out_dir / "ledger.jsonl", kind)
    cache = ResponseCache(out_dir / "cache", kind)
    extra = {"sleep": sleep} if sleep else {}
    gateway = Gateway(client, ledger, cache, budget_usd, **extra)

    rows: list[dict[str, Any]] = []
    stopped: str | None = None
    exit_code = 0
    reference_run.ensure_image()
    with reference_run.Container() as container:
        references = {}
        for case in cases:
            tuning = json.loads(case.tuning_path.read_text(encoding="utf-8"))
            heldout = json.loads(case.heldout_path.read_text(encoding="utf-8"))
            references[case.name] = {
                "tuning": reference_run.run_reference(case.source, tuning, container),
                "heldout": reference_run.run_reference(case.source, heldout, container),
            }
            rows.append(run_baseline(case, references[case.name], kind))

        for model, repeats in models:
            config = LlmConfig(model, effort, max_tokens, fallbacks)
            for case in cases:
                program = ProgramInput(case.name, case.source, case.tuning_path, references[case.name]["tuning"])
                for mode in modes:
                    for repeat in range(repeats):
                        if stopped:
                            rows.append(not_run_row(case, mode, config, repeat, kind))
                            continue
                        migration = migrate(program, mode, config, gateway, repeat)
                        if migration.stop_run:
                            stopped = migration.stop_run
                            exit_code = EXIT_BUDGET if migration.failure_category == "budget_stop" else EXIT_API
                            print(f"benchmark: stopping, {stopped}", file=sys.stderr)
                        rows.append(score(case, mode, config, repeat, kind, migration, references[case.name], out_dir))
                        forte_eval.prune_cache()
                        print(
                            f"{case.name} {mode} {model} r{repeat}: passed={rows[-1]['passed']} "
                            f"attempts={rows[-1]['attempts']} category={rows[-1]['failure_category']}",
                            flush=True,
                        )
                        # After every run, so that an interrupted benchmark still has a report.
                        write_reports(rows, kind, out_dir, stopped)
    return write_reports(rows, kind, out_dir, stopped), exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark LLM migration on real FORTE against matiec.")
    parser.add_argument("--programs", nargs="+", default=["all"], help="program names, or all")
    parser.add_argument("--modes", nargs="+", default=list(MODE_ATTEMPTS), choices=list(MODE_ATTEMPTS))
    parser.add_argument("--repeats", type=int, default=1, help="repeats per program, as independent samples")
    parser.add_argument("--model", nargs="+", default=[DEFAULT_MODEL], help="MODEL or MODEL:REPEATS, one or more")
    parser.add_argument("--effort", default=DEFAULT_EFFORT)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--no-fallbacks", action="store_true", help="do not opt in to server-side fallback")
    parser.add_argument("--budget-usd", type=float, help="total spend allowed by the ledger; required with --live")
    parser.add_argument("--live", action="store_true", help="make real API calls, which cost money")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and the worst-case cost, and call nothing")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, help="used only with --live")
    parser.add_argument("--corpus", type=Path, default=REPO / "corpus")
    parser.add_argument("--out-dir", type=Path, help="default build/llm for --live, build/llm/fake otherwise")
    args = parser.parse_args(argv)

    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    try:
        LlmConfig(DEFAULT_MODEL, args.effort, args.max_tokens)
    except ValueError as exc:
        parser.error(str(exc))
    cases = load_cases(args.corpus, args.programs)
    models = parse_models(args.model, args.repeats)

    if args.dry_run:
        return dry_run(cases, args.modes, models, args)

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
        out_dir = args.out_dir or LIVE_DIR
    else:
        client = echo_translator_client()
        out_dir = args.out_dir or FAKE_DIR
        print(f"benchmark: {FAKE_BANNER}", file=sys.stderr)

    document, code = run_benchmark(
        cases, args.modes, models, client, args.budget_usd, out_dir, args.effort, args.max_tokens, not args.no_fallbacks
    )
    print(f"wrote {out_dir / 'benchmark.json'} and {out_dir / 'benchmark.md'}, client={document['client']}")
    return code


if __name__ == "__main__":
    sys.exit(main())
