"""Check corpus_hard/ without any model: the oracle runs, the baseline does what we claim, and each program can be solved.

    python3 -m st2fb.llm.hard_check
    python3 -m st2fb.llm.hard_check --only s01_conveyor_starter

For each program this runs:
    translator           the translator on what the model sees: rejected or accepted, and if accepted, its result on FORTE
    frontend+translator  the same behind st2fb/vendor_frontend.py, on every scored stimulus
    oracle               matiec on the tuning and every held-out stimulus, and how much each output moves
    control              a known-good solution in the translator's v1 subset, on real FORTE against the oracle on all of them. If it
                         fails, a model failure on that program would say nothing. It is reference.st, control_flat.st, or for a program the
                         baseline accepts, the program itself. No control is shown to a model.
    start                a held-out file sharing more than one first scan with tuning fails the check.
For the ecc_persistent programs, it runs each hand-designed persistent control the same way and reports the metric.

Writes build/llm_hard/hard_check.json, with a manifest of the files checked if the whole corpus passed. A real benchmark on corpus_hard/ refuses to
start without that. Exit status 1 if anything fails or an unexplained output is static.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .. import fbt, forte_eval, reference_run
from ..translate import translate_source
from . import manifest
from .benchmark import ECC_PERSISTENT_PROGRAMS, HARD_LIVE_DIR, HELDOUT, REPO, TUNING, Case, frontend_tier, load_references, load_set
from .ecc_metric import ecc_persistence
from .heldout_check import transitions

HARD = REPO / "corpus_hard"
SETS = ("unsupported_st", "siemens_scl", "rockwell_st", "stress", "public_st")
OUT = manifest.RECORD
MAX_SHARED_START = 1  # Scans a held-out file may share with tuning from scan 0. More would let a scan count stand in for behaviour.
JOBS = 6
# Outputs allowed to stay constant on a stimulus, each with the reason. A static output tests nothing.
EXPLAINED_STATIC: dict[str, dict[str, str]] = {}


def control_source(case: Case, directory: Path) -> str | None:
    for name in ("control_flat.st", "reference.st"):
        path = directory / name
        if path.exists():
            return path.read_text(encoding="utf-8")
    return None


def check_case(case: Case, directory: Path, container: reference_run.Container) -> dict[str, Any]:
    references = load_references(case, container)
    tuning = json.loads(case.tuning_path.read_text(encoding="utf-8"))
    paths = {"tuning": case.tuning_path, **{path.stem: path for path in case.heldout_paths}}
    traces = {"tuning": references["tuning"], **{path.stem: trace for path, trace in zip(case.heldout_paths, references["heldout_all"])}}
    stimuli = {key: json.loads(path.read_text(encoding="utf-8")) for key, path in paths.items()}
    moves = {key: transitions(trace) for key, trace in traces.items()}
    static = {key: sorted(name for name, count in move.items() if count == 0) for key, move in moves.items()}
    explained = set(EXPLAINED_STATIC.get(case.name, {}))
    prefix = 0
    same_stimulus = False
    for path in case.heldout_paths:
        scans = stimuli[path.stem]["scans"]
        same_stimulus = same_stimulus or scans == tuning["scans"]
        shared = 0
        for a, b in zip(tuning["scans"], scans):
            if a != b:
                break
            shared += 1
        prefix = max(prefix, shared)

    frontend = frontend_tier(case, references)
    baseline: dict[str, Any]
    candidate: str | None = None
    try:
        candidate = fbt.write_fbt(translate_source(case.source))
        baseline = {"status": "accepted"}
    except ValueError as exc:
        baseline = {"status": "rejected", "reason": str(exc)}

    control_text = control_source(case, directory)
    if control_text is not None:
        control_fbt = fbt.write_fbt(translate_source(control_text))
    else:
        control_fbt = candidate  # Accepted by the translator, so the program is its own control.
    result = {
        "program": case.name,
        "set": case.set_name,
        "baseline": baseline,
        "frontend": frontend,
        "scans": {key: len(stimulus["scans"]) for key, stimulus in stimuli.items()},
        "scan_ms": {key: stimulus["scan_ms"] for key, stimulus in stimuli.items()},
        "identical_prefix_scans": prefix,
        "changes": {key: sum(move.values()) for key, move in moves.items()},
        "static": static,
        "unexplained_static": sorted(set().union(*static.values()) - explained),
        "same_stimulus": same_stimulus,
        "control": {},
    }
    if control_fbt is None:
        result["control"] = {key: "no control" for key in paths}
        return result
    for key, path in paths.items():
        result["control"][key] = forte_eval.evaluate(control_fbt, path, traces[key]).status
    if baseline["status"] == "accepted":
        outcomes = [forte_eval.evaluate(candidate, path, traces[key]) for key, path in paths.items()]
        baseline["result"] = "passed" if all(outcome.equal for outcome in outcomes) else "failed"
    return result


def case_failed(result: dict[str, Any]) -> bool:
    return (
        any(status != "equal" for status in result["control"].values())
        or bool(result["unexplained_static"])
        or result["same_stimulus"]
        or result["identical_prefix_scans"] > MAX_SHARED_START
    )


def check_ecc(name: str, container: reference_run.Container) -> dict[str, Any]:
    directory = REPO / "corpus" / name
    source = (directory / "program.st").read_text(encoding="utf-8")
    text = (HARD / "ecc_persistent" / name / "control.fbt").read_text(encoding="utf-8")
    result: dict[str, Any] = {"program": name, **ecc_persistence(text), "control": {}}
    for key, file_name in (("tuning", TUNING), ("heldout", HELDOUT)):
        path = directory / file_name
        trace = reference_run.run_reference(source, json.loads(path.read_text(encoding="utf-8")), container)
        result["control"][key] = forte_eval.evaluate(text, path, trace).status
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="*", help="only these programs")
    args = parser.parse_args(argv)
    jobs = []
    for set_name in SETS:
        directory = HARD / set_name
        if (directory / "set.json").exists():
            for case in load_set(directory):
                if not args.only or case.name in args.only:
                    jobs.append((case, directory / case.name))
    reference_run.ensure_image()
    with reference_run.Container() as container, ThreadPoolExecutor(max_workers=JOBS) as pool:
        results = list(pool.map(lambda job: check_case(job[0], job[1], container), jobs))
        names = [name for name in ECC_PERSISTENT_PROGRAMS if not args.only or name in args.only]
        ecc = list(pool.map(lambda name: check_ecc(name, container), names))
    failed = False
    for r in results:
        base = r["baseline"]
        verdict = f"accepted, {base.get('result')}" if base["status"] == "accepted" else "rejected"
        print(
            f"{r['set']:15} {r['program']:26} translator {verdict:18} frontend+translator {r['frontend']['frontend_status']:9} control {'/'.join(r['control'].values())} "
            f"scans {'/'.join(map(str, r['scans'].values()))} at {'/'.join(map(str, r['scan_ms'].values()))} ms prefix {r['identical_prefix_scans']} changes {'/'.join(map(str, r['changes'].values()))} static {r['unexplained_static']}"
        )
        failed = failed or case_failed(r)
    for r in ecc:
        print(
            f"ecc_persistent  {r['program']:26} metric {r['ecc_verdict']} control states {r['control_states']} control {r['control']['tuning']}/{r['control']['heldout']} {r['ecc_persistent_failures']} {r['ecc_needs_reading']}"
        )
        if r["control"] != {"tuning": "equal", "heldout": "equal"} or r["ecc_verdict"] != "persistent":
            failed = True
    whole = not args.only and not failed
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"passed": whole, "manifest": manifest.compute() if whole else None, "programs": results, "ecc_persistent": ecc}, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT}. {'Passed: the manifest is recorded, and a benchmark may run.' if whole else 'No pass recorded: a benchmark will refuse to run.'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
