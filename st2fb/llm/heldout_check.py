"""Check that the held-out stimuli are meaningful, using the deterministic translator as the control.

    python3 -m st2fb.llm.heldout_check

For each program: the deterministic translation must equal matiec on the held-out stimulus, the
held-out scans must differ from the tuning scans, and no output may be static on held-out unless it is
already static on tuning. Writes build/llm/heldout_check.json. Exit status 1 if a program fails the first two.
A newly static output is reported as an exception and does not fail the run, because it may have a reason.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .. import fbt, forte_eval, reference_run
from ..translate import translate_source

REPO = Path(__file__).resolve().parent.parent.parent
OUT = REPO / "build" / "llm" / "heldout_check.json"
TUNING, HELDOUT = "stimulus.json", "heldout_stimulus.json"
JOBS = 6


def transitions(trace: dict[str, Any]) -> dict[str, int]:
    counts = {}
    for name in trace["outputs"]:
        values = [scan[name] for scan in trace["scans"]]
        counts[name] = sum(a != b for a, b in zip(values, values[1:]))
    return counts


def check_program(directory: Path, container: reference_run.Container) -> dict[str, Any]:
    source = (directory / "program.st").read_text(encoding="utf-8")
    tuning = json.loads((directory / TUNING).read_text(encoding="utf-8"))
    heldout = json.loads((directory / HELDOUT).read_text(encoding="utf-8"))
    tuning_trace = reference_run.run_reference(source, tuning, container)
    heldout_trace = reference_run.run_reference(source, heldout, container)
    outcome = forte_eval.evaluate(fbt.write_fbt(translate_source(source)), directory / HELDOUT, heldout_trace)
    moves_tuning = transitions(tuning_trace)
    moves_heldout = transitions(heldout_trace)
    tuning_rows = {json.dumps(scan, sort_keys=True) for scan in tuning["scans"]}
    shared = sum(json.dumps(scan, sort_keys=True) in tuning_rows for scan in heldout["scans"])
    identical_prefix = 0
    for a, b in zip(tuning["scans"], heldout["scans"]):
        if a != b:
            break
        identical_prefix += 1
    return {
        "program": directory.name,
        "status": outcome.status,
        "divergences": outcome.report["divergences"] if outcome.report else None,
        "scans_tuning": len(tuning["scans"]),
        "scans_heldout": len(heldout["scans"]),
        "identical_prefix_scans": identical_prefix,
        "heldout_scans_also_in_tuning": shared,
        "changes_tuning": sum(moves_tuning.values()),
        "changes_heldout": sum(moves_heldout.values()),
        "static_tuning": sorted(k for k, v in moves_tuning.items() if v == 0),
        "static_heldout": sorted(k for k, v in moves_heldout.items() if v == 0),
        "newly_static": sorted(k for k, v in moves_heldout.items() if v == 0 and moves_tuning[k] != 0),
        "same_stimulus": tuning["scans"] == heldout["scans"],
    }


def main() -> int:
    directories = sorted(path.parent for path in (REPO / "corpus").glob("*/program.st"))
    reference_run.ensure_image()
    with reference_run.Container() as container, ThreadPoolExecutor(max_workers=JOBS) as pool:
        results = list(pool.map(lambda d: check_program(d, container), directories))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    for r in results:
        print(
            f"{r['program']:30} {r['status']:10} scans {r['scans_tuning']:5}/{r['scans_heldout']:5} "
            f"prefix={r['identical_prefix_scans']:3} changes {r['changes_tuning']:5}/{r['changes_heldout']:5} "
            f"static tuning={r['static_tuning']} heldout={r['static_heldout']} newly={r['newly_static']}"
        )
    equal = sum(r["status"] == "equal" for r in results)
    same = [r["program"] for r in results if r["same_stimulus"]]
    print(f"{equal}/{len(results)} equal on held-out. Same as tuning: {same}. Newly static: "
          f"{[(r['program'], r['newly_static']) for r in results if r['newly_static']]}")
    return 0 if equal == len(results) and not same else 1


if __name__ == "__main__":
    sys.exit(main())
