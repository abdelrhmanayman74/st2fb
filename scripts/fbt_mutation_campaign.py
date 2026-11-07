#!/usr/bin/env python3
"""Mutate the ST inside each translated .fbt, run it on real FORTE, compare with unmutated matiec.

    python3 scripts/fbt_mutation_campaign.py --count 5 --seed 61499 --jobs 6 \
        --report docs/FBT_MUTATION_RESULTS.md --save-json corpus/fbt_mutation_results.json

`python3 -m st2fb.mutate campaign` compares matiec with mutated matiec and never touches FORTE, so it
says nothing about the FORTE path. This one exercises the whole forward path: translator output,
exporter, g++, FORTE, FBDK driver, compare.

A mutant is counted as detected if its trace differs from the reference, if it crashes, or if it times
out. Compile failures say nothing about the comparison, so they are counted separately. The ECC is not
mutated: the translator's only guards are REQ and 1, and a mutation of either is a missing or surplus
CNF that the driver reports without any trace comparison.

A survivor is re-run on the held-out stimulus if the program has one, which is extra evidence about the
survivor and does not change the score. Binaries of mutants are deleted after use, since each is 24 MB.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from st2fb import fbt, forte_eval, forte_run, reference_run  # noqa: E402
from st2fb.mutate import fbt_mutants, oracle_file, program_dirs, select_mutants  # noqa: E402
from st2fb.translate import translate_source  # noqa: E402
from st2fb.vendor_frontend import to_plain_st  # noqa: E402

MAX_JOBS = 6  # This machine has to stay usable, and each job is a g++ run and a FORTE container.
HELDOUT_NAME = "heldout_stimulus.json"
DETECTED = ("killed", "crashed", "timed_out")
STATUS_TO_OUTCOME = {
    "different": "killed",
    "equal": "survived",
    "crashed": "crashed",
    "timed_out": "timed_out",
    "compile_failed": "compile_failed",
    "infra_failed": "infra_failed",
}


def run_mutant(text: str, stimulus: Path, reference: dict[str, Any], keep_binaries: frozenset[Path]) -> dict[str, Any]:
    outcome = forte_eval.evaluate(text, stimulus, reference)
    if outcome.binary_dir is not None and outcome.binary_dir not in keep_binaries:
        shutil.rmtree(outcome.binary_dir, ignore_errors=True)
    if outcome.status not in STATUS_TO_OUTCOME:
        # A mutant only edits an algorithm body, so the XML and the interface cannot have broken.
        raise RuntimeError(f"mutation broke the pipeline: {outcome.status}: {outcome.detail}")
    result: dict[str, Any] = {"outcome": STATUS_TO_OUTCOME[outcome.status]}
    if outcome.status not in ("equal",):
        result["detail"] = (
            json.dumps(outcome.report["first_divergence"]) if outcome.report else outcome.detail.strip()[-300:]
        )
    return result


def hard_base(program_dir: Path) -> tuple[str, str]:
    """What to mutate on corpus_hard/: the front-end's translation where it gets through, otherwise the solvability control. Never a model's reply."""
    settings = json.loads((program_dir.parent / "set.json").read_text(encoding="utf-8"))
    source = (program_dir / settings["source_file"]).read_text(encoding="utf-8")
    try:
        return fbt.write_fbt(translate_source(to_plain_st(source, settings["dialect"]))), "frontend+translator"
    except ValueError:
        return fbt.write_fbt(translate_source((program_dir / "control_flat.st").read_text(encoding="utf-8"))), "control_flat.st"


def run_program(
    program_dir: Path, count: int, seed: int, pool: ThreadPoolExecutor, container: reference_run.Container, hard: bool = False
) -> dict[str, Any]:
    name = program_dir.name
    st_text = (oracle_file(program_dir) if hard else program_dir / "program.st").read_text(encoding="utf-8")
    stimulus_path = program_dir / "stimulus.json"
    stimulus = json.loads(stimulus_path.read_text(encoding="utf-8"))
    reference = reference_run.run_reference(st_text, stimulus, container)
    base, base_from = hard_base(program_dir) if hard else (fbt.write_fbt(translate_source(st_text)), "translator")

    # Control: without this a "kill" could just be a translation that is wrong anyway.
    control = forte_eval.evaluate(base, stimulus_path, reference)
    available = fbt_mutants(base, stimulus["scan_ms"])
    selected = select_mutants(available, count, f"{seed}:{name}")
    keep = frozenset({control.binary_dir} if control.binary_dir else set())
    outcomes = list(pool.map(lambda m: run_mutant(m.text, stimulus_path, reference, keep), selected))

    # Second look at survivors, on a stimulus the campaign did not select them with. On corpus_hard/ a survivor has to survive every held-out file.
    survivors = [(m, o) for m, o in zip(selected, outcomes) if o["outcome"] == "survived"]
    heldout_paths = [path for path in sorted(program_dir.glob("heldout_stimulus*.json")) if hard or path.name == HELDOUT_NAME]
    for heldout_path in heldout_paths if survivors else []:
        heldout = json.loads(heldout_path.read_text(encoding="utf-8"))
        heldout_reference = reference_run.run_reference(st_text, heldout, container)
        again = pool.map(lambda pair: run_mutant(pair[0].text, heldout_path, heldout_reference, keep), survivors)
        for (_, outcome), second in zip(survivors, again):
            if outcome.get("heldout_outcome", "survived") == "survived":
                outcome["heldout_outcome"] = second["outcome"]
                if "detail" in second:
                    outcome["heldout_detail"] = second["detail"]

    return {
        "program": name,
        "base": base_from,
        "scans": len(stimulus["scans"]),
        "available": len(available),
        "control": control.status,
        "mutants": [
            {"kind": m.kind, "description": m.description, **outcome} for m, outcome in zip(selected, outcomes)
        ],
    }


def tally(mutants: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"killed": 0, "crashed": 0, "timed_out": 0, "survived": 0, "compile_failed": 0, "infra_failed": 0}
    for mutant in mutants:
        counts[mutant["outcome"]] += 1
    return counts


def rate(counts: dict[str, int]) -> str:
    detected = sum(counts[key] for key in DETECTED)
    total = detected + counts["survived"]
    return f"{100.0 * detected / total:.1f}%" if total else "n/a"


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def render_report(results: list[dict[str, Any]], count: int, seed: int, notes: dict[str, Any], seconds: float) -> str:
    everything = [mutant for result in results for mutant in result["mutants"]]
    overall = tally(everything)
    detected = sum(overall[key] for key in DETECTED)
    counted = detected + overall["survived"]
    hard = any(result.get("base", "translator") != "translator" for result in results)
    lines = [
        "# FORTE mutation results",
        "",
        "Generated by `python3 scripts/fbt_mutation_campaign.py`. Do not edit by hand, except through",
        f"`{'corpus_hard' if hard else 'corpus'}/fbt_mutation_survivor_notes.json`.",
        "",
        *([
            "Each mutant is one edit to the ST algorithm text of the .fbt that the small front-end plus the translator produce, or of the solvability control where the front-end does not get through.",
            "It runs through the exporter, g++ and **real FORTE**, and its trace is compared with **unmutated matiec** on the tuning stimulus. Survivors are run again on every held-out file. This is a sample of about",
            "5 per program, and different from `docs/HARD_MUTATION_RESULTS.md`, which compares matiec with mutated matiec and does not involve FORTE. No model's output is involved.",
        ] if hard else [
            "Each mutant is one edit to the ST algorithm text of the deterministic translator's .fbt. It runs through",
            "the exporter, g++ and **real FORTE**, and its trace is compared with **unmutated matiec**. This is a",
            "different experiment from `docs/MUTATION_RESULTS.md`, which compares matiec with mutated matiec and does",
            "not involve FORTE.",
        ]),
        "",
        f"Run with `--count {count} --seed {seed}`, in {seconds:.0f} s.",
        "",
        f"**Detected: {detected} of {counted} counted mutants ({rate(overall)})**: {overall['killed']} different, "
        f"{overall['crashed']} crashed, {overall['timed_out']} timed out. {overall['survived']} survived. "
        f"{overall['compile_failed']} failed to compile and are not counted.",
    ]
    if overall["infra_failed"]:
        lines += ["", f"**{overall['infra_failed']} runs failed for infrastructure reasons and are not counted.**"]
    lines += [
        "",
        "How to read this:",
        "",
        f"- {len(results)} programs at {count} mutants each is a small sample, far smaller than the exhaustive matiec",
        "  campaign. A confidence interval on a rate from this few mutants would be wide.",
        "- `select_mutants` takes kinds in sorted order, so at 5 per program it takes boundary, constant, negate,",
        "  operator and remove in turn. Branch swaps are not sampled at this count unless a program lacks one of",
        "  those kinds. The kind table below shows what was actually run.",
        "- The .fbt text includes the lowered standard FBs, so some mutants hit the timer and counter logic that the",
        "  translator inlined. The ST-level campaign cannot reach those lines.",
        "- The corpus is self-authored. See `docs/CORPUS.md`.",
        "- The ECC is not mutated. The translator's only guards are `REQ` and `1`, so there is nothing to mutate in",
        "  it that is more interesting than a missing CNF, which `tests/test_forward_e2e.py` already covers.",
        "",
        "## Per program",
        "",
        "| Program | Scans | Available | Selected | Compile-failed | Total counted | Killed | Crashed | Timed out | Survived | Control |",
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|",
    ]
    for result in results:
        c = tally(result["mutants"])
        total = sum(c[key] for key in DETECTED) + c["survived"]
        lines.append(
            f"| {result['program']} | {result['scans']} | {result['available']} | {len(result['mutants'])} "
            f"| {c['compile_failed']} | {total} | {c['killed']} | {c['crashed']} | {c['timed_out']} "
            f"| {c['survived']} | {result['control']} |"
        )
    lines += [
        "",
        "## By mutation kind",
        "",
        "| Kind | Compile-failed | Total counted | Detected | Survived |",
        "|---|--:|--:|--:|--:|",
    ]
    for kind in sorted({mutant["kind"] for mutant in everything}):
        c = tally([mutant for mutant in everything if mutant["kind"] == kind])
        found = sum(c[key] for key in DETECTED)
        lines.append(f"| {kind} | {c['compile_failed']} | {found + c['survived']} | {found} | {c['survived']} |")

    survivor_notes = notes.get("survivors", {})
    survivors = [(r["program"], m) for r in results for m in r["mutants"] if m["outcome"] == "survived"]
    lines += ["", "## Survivors", ""]
    if survivors:
        lines += [
            "Each analysis is a reasoned argument from reading the program and the mutant. It is not a proof, and no",
            "equivalence checker was run. `Held-out` is the result of re-running that mutant on",
            "`heldout_stimulus.json`, which is evidence and is not counted in the score above.",
            "",
            "| Program | Mutant | Held-out | Analysis |",
            "|---|---|---|---|",
        ]
        for program, mutant in survivors:
            analysis = survivor_notes.get(f"{program}|{mutant['description']}", "Not analysed.")
            lines.append(
                f"| {program} | `{_cell(mutant['description'])}` | {mutant.get('heldout_outcome', 'not run')} | {analysis} |"
            )
    else:
        lines.append("None.")

    failed = [(r["program"], m) for r in results for m in r["mutants"] if m["outcome"] == "compile_failed"]
    if failed:
        lines += ["", "## Compile failures", "", "| Program | Mutant | Rejected by |", "|---|---|---|"]
        for program, mutant in failed:
            lines.append(f"| {program} | `{_cell(mutant['description'])}` | {_cell(mutant.get('detail', ''))[:200]} |")

    if notes.get("earlier"):
        lines += ["", "## Earlier survivors, from before this campaign", ""]
        for title, body in notes["earlier"].items():
            lines += [f"### {title}", "", *body, ""]
    if notes.get("findings"):
        lines += ["", "## Findings", ""]
        lines += notes["findings"]
    return "\n".join(line for line in lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mutated .fbt on real FORTE against unmutated matiec.")
    parser.add_argument("--corpus", default=str(REPO / "corpus"))
    parser.add_argument("--count", type=int, default=5, help="mutants selected per program")
    parser.add_argument("--seed", type=int, default=61499)
    parser.add_argument("--jobs", type=int, default=MAX_JOBS, help=f"parallel FORTE builds, at most {MAX_JOBS}")
    parser.add_argument("--only", nargs="*", help="restrict to these program directories")
    parser.add_argument("--report", help="Markdown report to write")
    parser.add_argument("--save-json", help="raw results to write")
    parser.add_argument("--from-json", help="render the report from earlier raw results, without running")
    parser.add_argument("--notes", default=str(REPO / "corpus" / "fbt_mutation_survivor_notes.json"))
    args = parser.parse_args(argv)
    notes_path = Path(args.notes)
    notes = json.loads(notes_path.read_text(encoding="utf-8")) if notes_path.exists() else {}

    if args.from_json:
        saved = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        text = render_report(saved["results"], saved["count"], saved["seed"], notes, saved["seconds"])
        Path(args.report).write_text(text, encoding="utf-8")
        return 0

    jobs = min(args.jobs, MAX_JOBS)
    hard = Path(args.corpus).resolve() == (REPO / "corpus_hard").resolve()
    programs = program_dirs(Path(args.corpus)) if hard else sorted(path.parent for path in Path(args.corpus).glob("*/program.st"))
    if args.only:
        programs = [path for path in programs if path.name in args.only]
    reference_run.ensure_image()
    forte_run.ensure_image()
    started = time.monotonic()
    results = []
    # Mutants are what grow the cache, and no evaluation is running yet, so this is the safe moment to prune.
    forte_eval.prune_cache()
    with ThreadPoolExecutor(max_workers=jobs) as pool, reference_run.Container() as container:
        for program_dir in programs:
            result = run_program(program_dir, args.count, args.seed, pool, container, hard)
            print(f"{result['program']}: control {result['control']}, {tally(result['mutants'])}", flush=True)
            results.append(result)
            if args.save_json:  # After every program, so an interrupted run keeps what it did.
                out = Path(args.save_json)
                out.parent.mkdir(parents=True, exist_ok=True)
                document = {"count": args.count, "seed": args.seed, "seconds": time.monotonic() - started, "results": results}
                out.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    seconds = time.monotonic() - started

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(render_report(results, args.count, args.seed, notes, seconds), encoding="utf-8")
    overall = tally([m for r in results for m in r["mutants"]])
    print(f"overall {overall}, rate {rate(overall)}, {seconds:.0f} s")
    controls_ok = all(result["control"] == "equal" for result in results)
    return 0 if controls_ok and overall["infra_failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
