# st2fb design: IEC 61131-3 ST to IEC 61499 migration with behavioural proof

Goal: take a cyclic Structured Text function block, produce an IEC 61499 Basic FB (.fbt),
run it on the real Eclipse 4diac FORTE runtime, and prove it matches the original by
comparing traces against an independent reference (matiec).

```
program.st --(baseline translator or LLM)--> X.fbt --(exporter)--> FORTE C++ --> forte_run --> trace.json
     \------------------------------------(matiec)-----------------> reference_run ---> trace.json
                                                        compare(trace, trace) --> report.json
```

The LLM never decides correctness. Any .fbt, from any source, goes through the same exporter
and comparison. Baseline, LLM-only and LLM-with-repair are benchmarked on identical inputs.

## Scope v1
- Types: BOOL, INT, DINT, UINT, REAL, TIME. No arrays, strings or structs yet.
- Statements: assignment, IF/ELSIF/ELSE, CASE, FOR, WHILE, RETURN-free bodies.
- Standard FBs usable in source ST: TON, TOF, TP, R_TRIG, F_TRIG, CTU, CTD, SR, RS.
- One FUNCTION_BLOCK per program.st, with VAR_INPUT, VAR_OUTPUT and VAR.

`corpus_hard/` deliberately goes beyond this scope in its sources: the model has to rewrite them into it. See `docs/HARD_CORPUS.md`.

## Contract (all parts must follow this exactly)

Pinned runtime: eclipse-4diac/4diac-forte commit efcd63c. Builds on ubuntu:24.04 with g++ 13,
Ninja from apt and CMake >= 3.30 from pip, using -DFORTE_ARCHITECTURE=Posix (verified).
Reference compiler: beremiz/matiec commit 3a41303. It is GPLv3, so it is only invoked as an
external tool inside a container and is never linked or vendored.

Corpus: `corpus/<name>/program.st`, `corpus/<name>/stimulus.json`, optional `corpus/<name>/README.md`.
A file with helper blocks marks the block under test with the comment `(* st2fb:dut *)` just before its `FUNCTION_BLOCK`.

stimulus.json:
    {"scan_ms": 10, "scans": [{"S": true, "R": false}, ...]}
Every scan lists every VAR_INPUT. Values: JSON bool, number; TIME in integer milliseconds.
One file has one scan period. A program that needs scoring at more than one period has more than one file: `corpus_hard/` scores
`heldout_stimulus.json` and `heldout_stimulus_2.json`, at different periods, and a run must pass both. See `docs/HARD_CORPUS.md`.

trace.json (both runners produce this, and only this):
    {"source": "forte|matiec", "scan_ms": 10, "outputs": ["Q"],
     "scans": [{"t_ms": 0, "Q": false}, ...]}
One record per scan, read after that scan completes. t_ms = scan index * scan_ms.
REAL is emitted as a JSON number; TIME as integer milliseconds.

.fbt: standard IEC 61499 XML as used by 4diac (see corpus/00_latch/expected.fbt).
- Event input REQ with every data input; event output CNF with every data output.
- The exporter must support GENERAL Basic FBs: multiple EC states, guarded transitions
  (`REQ[x > 3]`, `[cond]`, `1`), multiple algorithms, multiple actions per state. LLM output will
  restructure CASE state machines into real ECC states, so a one-state-only exporter is not enough.
- Baseline translation is the safe form: START -> RUN on REQ, RUN runs algorithm `scan` and
  emits CNF, RUN -> START on 1.

Time and determinism: migrated FBs must not read a wall clock. When the source uses a timer,
the translator adds input `SCAN_DT : TIME` and lowers the timer to inline ST on internal variables.
forte_run sets SCAN_DT = scan_ms each scan. Lowered semantics must match matiec's standard library
as observed; differences must be resolved by reading matiec's lib, not by adding tolerance.
All other standard FBs are also lowered to inline ST on internal variables.

CLIs (run from the repo root; each writes its output file and exits non-zero on failure):
    python3 -m st2fb.translate corpus/X/program.st --out build/X/X.fbt
    python3 -m st2fb.forte_run --fbt build/X/X.fbt --stimulus corpus/X/stimulus.json --out build/X/forte.json
    python3 -m st2fb.reference_run --st corpus/X/program.st --stimulus corpus/X/stimulus.json --out build/X/matiec.json
    python3 -m st2fb.compare build/X/matiec.json build/X/forte.json --out build/X/report.json

report.json:
    {"equal": bool, "scans_compared": n, "first_divergence":
       {"scan": i, "t_ms": t, "output": "Q", "expected": v, "actual": w} | null,
     "divergences": n, "real_tolerance": 1e-5}
Comparison is exact except REAL (relative tolerance, default 1e-5). No time tolerance.

Honesty rules: no invented results. Numbers in reports come from running the code. A runner must
execute real FORTE or real matiec, never a Python simulation of them.
