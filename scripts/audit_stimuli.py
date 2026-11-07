#!/usr/bin/env python3
"""List every numeric input of corpus_hard/ that a scored stimulus does not really exercise.

    python3 scripts/audit_stimuli.py

A numeric input with one value across all scored stimuli tests nothing, and a migration could freeze it. An input with no value on held-out that
tuning lacks cannot show whether a migration generalised. So this exits 1 if any numeric input is constant across the scored stimuli, or if a held-out
file holds no new value for it. Each scan period is also listed, since the period is an input too, by way of SCAN_DT or TaskPeriodMs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from st2fb.mutate import oracle_file, program_dirs, scored_stimuli  # noqa: E402
from st2fb.reference_run import scan_interface  # noqa: E402

NUMERIC = {"INT", "DINT", "UINT", "REAL", "TIME"}


def audit(program_dir: Path) -> list[dict[str, object]]:
    interface = scan_interface(oracle_file(program_dir).read_text(encoding="utf-8"))
    paths = scored_stimuli(program_dir)
    stimuli = {path.name: json.loads(path.read_text(encoding="utf-8"))["scans"] for path in paths}
    rows = []
    for var in interface.inputs:
        if var.type in NUMERIC:
            tuning = {scan[var.name] for scan in stimuli["stimulus.json"]}
            heldout = {scan[var.name] for name, scans in stimuli.items() if name != "stimulus.json" for scan in scans}
            rows.append({"name": var.name, "type": var.type, "tuning": len(tuning), "heldout": len(heldout), "new_on_heldout": len(heldout - tuning), "constant": len(tuning | heldout) == 1})
    return rows


def main() -> int:
    failed = False
    for program_dir in program_dirs(REPO / "corpus_hard"):
        periods = sorted({json.loads(path.read_text(encoding="utf-8"))["scan_ms"] for path in scored_stimuli(program_dir)})
        rows = audit(program_dir)
        print(f"{program_dir.name}: scan periods {periods}")
        for row in rows:
            flag = "CONSTANT" if row["constant"] else "NO NEW VALUE" if not row["new_on_heldout"] else "ok"
            failed = failed or flag != "ok"
            print(f"  {row['name']:22} {row['type']:5} values on tuning {row['tuning']:4}  on held-out {row['heldout']:4}  new on held-out {row['new_on_heldout']:4}  {flag}")
    print("FAILED: some numeric input is not exercised." if failed else "Every numeric input varies across the scored stimuli, and has a value on held-out that tuning lacks.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
