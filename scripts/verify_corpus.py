#!/usr/bin/env python3
"""Run every corpus program through the full pipeline and summarise the evidence.

A pass needs equal traces from FORTE and matiec. The script also reports how many times
each output changes, because traces that barely move can match without proving much.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "verify"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", *args], cwd=ROOT, capture_output=True, text=True)


def transitions(trace: dict) -> dict:
    """Count value changes per output across the scans."""
    counts = {}
    for name in trace["outputs"]:
        values = [scan[name] for scan in trace["scans"]]
        counts[name] = sum(a != b for a, b in zip(values, values[1:]))
    return counts


def verify(program: Path) -> dict:
    name = program.parent.name
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    fbt, forte, matiec, report = (out / f for f in (f"{name}.fbt", "forte.json", "matiec.json", "report.json"))
    for path in (fbt, forte, matiec, report):
        path.unlink(missing_ok=True)
    stimulus = str(program.parent / "stimulus.json")
    steps = [
        ("translate", ("st2fb.translate", str(program), "--out", str(fbt))),
        ("forte", ("st2fb.forte_run", "--fbt", str(fbt), "--stimulus", stimulus, "--out", str(forte))),
        ("matiec", ("st2fb.reference_run", "--st", str(program), "--stimulus", stimulus, "--out", str(matiec))),
        ("compare", ("st2fb.compare", str(matiec), str(forte), "--out", str(report))),
    ]
    for label, args in steps:
        result = run(*args)
        if result.returncode != 0 and not (label == "compare" and result.returncode == 1):
            return {"program": name, "ok": False, "failed_step": label, "error": result.stderr[-500:]}
    summary = json.loads(report.read_text())
    expected = json.loads(matiec.read_text())
    moves = transitions(expected)
    return {
        "program": name,
        "ok": summary["equal"],
        "scans": summary["scans_compared"],
        "divergences": summary["divergences"],
        "outputs": len(moves),
        "static_outputs": [k for k, v in moves.items() if v == 0],
        "output_changes": sum(moves.values()),
    }


def main() -> int:
    started = time.time()
    results = [verify(p) for p in sorted((ROOT / "corpus").glob("*/program.st"))]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(results, indent=1))
    for r in results:
        if "failed_step" in r:
            print(f"{r['program']:32} FAILED at {r['failed_step']}: {r['error']}")
        else:
            state = "EQUAL" if r["ok"] else f"DIFFERENT ({r['divergences']})"
            print(f"{r['program']:32} {state:12} scans={r['scans']:5} outputs={r['outputs']:2} "
                  f"changes={r['output_changes']:5} static={r['static_outputs']}")
    passed = sum(bool(r["ok"]) for r in results)
    print(f"{passed}/{len(results)} equal in {time.time() - started:.0f}s")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
