#!/usr/bin/env python3
"""Does a result depend on a disputed reading of a vendor instruction? matiec on the reference, against matiec with that one reading changed.

    python3 scripts/check_vendor_readings.py

The oracle for a vendor program is matiec's run of a hand translation, and matiec's standard library is not Siemens's. So for each reading someone could reasonably take of an
instruction, this swaps in a helper block with that reading, and looks for any difference on any scored stimulus. `same` means the program's score does not depend on that
reading, on these stimuli. It does not mean the reading is settled, or that the program matches a real S7 controller. The Logix instructions are invented, so a difference there
means only that the program depends on what the dialect file says: see docs/HARD_CORPUS.md, which lists these per program.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from st2fb import reference_run  # noqa: E402
from st2fb.compare import compare_traces  # noqa: E402
from st2fb.mutate import program_dirs, scored_stimuli  # noqa: E402

TIMER_INTERFACE = """
  VAR_INPUT IN : BOOL; PT : TIME; END_VAR
  VAR_OUTPUT Q : BOOL := FALSE; ET : TIME := T#0s; END_VAR
"""
CLOCK = "{__SET_VAR(data__->,CURRENT_TIME,,__CURRENT_TIME)}"
STATE_VARS = "VAR STATE : SINT := 0; PREV_IN : BOOL := FALSE; CURRENT_TIME, START_TIME, PT_HELD : TIME; END_VAR"
VARIANTS = {
    "TON PT sampled on the rising edge": (r":\s*TON\s*;", ": TON_X;", f"""FUNCTION_BLOCK TON_X{TIMER_INTERFACE}  {STATE_VARS}
  {CLOCK}
  IF ((STATE = 0) AND NOT(PREV_IN) AND IN) THEN STATE := 1; Q := FALSE; START_TIME := CURRENT_TIME; PT_HELD := PT;
  ELSE IF (NOT(IN)) THEN ET := T#0s; Q := FALSE; STATE := 0;
    ELSIF (STATE = 1) THEN IF ((START_TIME + PT_HELD) <= CURRENT_TIME) THEN STATE := 2; Q := TRUE; ET := PT_HELD; ELSE ET := CURRENT_TIME - START_TIME; END_IF; END_IF;
  END_IF;
  PREV_IN := IN;
END_FUNCTION_BLOCK
"""),
    "TON PT live after expiry (raising PT clears Q)": (r":\s*TON\s*;", ": TON_X;", f"""FUNCTION_BLOCK TON_X{TIMER_INTERFACE}  {STATE_VARS}
  {CLOCK}
  IF ((STATE = 0) AND NOT(PREV_IN) AND IN) THEN STATE := 1; Q := FALSE; START_TIME := CURRENT_TIME;
  ELSE IF (NOT(IN)) THEN ET := T#0s; Q := FALSE; STATE := 0;
    ELSIF (STATE = 1) OR (STATE = 2) THEN IF ((START_TIME + PT) <= CURRENT_TIME) THEN STATE := 2; Q := TRUE; ET := PT; ELSE STATE := 1; Q := FALSE; ET := CURRENT_TIME - START_TIME; END_IF; END_IF;
  END_IF;
  PREV_IN := IN;
END_FUNCTION_BLOCK
"""),
    "TOF PT sampled on the falling edge": (r":\s*TOF\s*;", ": TOF_X;", f"""FUNCTION_BLOCK TOF_X{TIMER_INTERFACE}  {STATE_VARS}
  {CLOCK}
  IF ((STATE = 0) AND PREV_IN AND NOT(IN)) THEN STATE := 1; START_TIME := CURRENT_TIME; PT_HELD := PT;
  ELSE IF IN THEN ET := T#0s; STATE := 0;
    ELSIF (STATE = 1) THEN IF ((START_TIME + PT_HELD) <= CURRENT_TIME) THEN STATE := 2; ET := PT_HELD; ELSE ET := CURRENT_TIME - START_TIME; END_IF; END_IF;
  END_IF;
  Q := IN OR (STATE = 1);
  PREV_IN := IN;
END_FUNCTION_BLOCK
"""),
    "TP PT sampled on the rising edge": (r":\s*TP\s*;", ": TP_X;", f"""FUNCTION_BLOCK TP_X{TIMER_INTERFACE}  {STATE_VARS}
  {CLOCK}
  IF ((STATE = 0) AND NOT(PREV_IN) AND IN) THEN STATE := 1; Q := TRUE; START_TIME := CURRENT_TIME; PT_HELD := PT;
  ELSIF (STATE = 1) THEN IF ((START_TIME + PT_HELD) <= CURRENT_TIME) THEN STATE := 2; Q := FALSE; ET := PT_HELD; ELSE ET := CURRENT_TIME - START_TIME; END_IF;
  END_IF;
  IF ((STATE = 2) AND NOT(IN)) THEN ET := T#0s; STATE := 0; END_IF;
  PREV_IN := IN;
END_FUNCTION_BLOCK
"""),
    "CTU counts past PV to the type limit": (r":\s*CTU\s*;", ": CTU_X;", """FUNCTION_BLOCK CTU_X
  VAR_INPUT CU : BOOL; R : BOOL; PV : INT; END_VAR
  VAR_OUTPUT Q : BOOL; CV : INT; END_VAR
  VAR CU_T : R_TRIG; END_VAR
  CU_T(CLK := CU);
  IF R THEN CV := 0; ELSIF CU_T.Q AND (CV < 32767) THEN CV := CV + 1; END_IF;
  Q := CV >= PV;
END_FUNCTION_BLOCK
"""),
    "F_TRIG gives no pulse on the first scan": (r":\s*F_TRIG\s*;", ": F_TRIG_X;", """FUNCTION_BLOCK F_TRIG_X
  VAR_INPUT CLK : BOOL; END_VAR
  VAR_OUTPUT Q : BOOL; END_VAR
  VAR M : BOOL; INIT : BOOL; END_VAR
  IF NOT INIT THEN M := TRUE; INIT := TRUE; END_IF;
  Q := NOT CLK AND NOT M;
  M := NOT CLK;
END_FUNCTION_BLOCK
"""),
    "RS gives set priority": (r":\s*RS\s*;", ": RS_X;", """FUNCTION_BLOCK RS_X
  VAR_INPUT S : BOOL; R1 : BOOL; END_VAR
  VAR_OUTPUT Q1 : BOOL; END_VAR
  Q1 := S OR (NOT R1 AND Q1);
END_FUNCTION_BLOCK
"""),
    "SR gives reset priority": (r":\s*SR\s*;", ": SR_X;", """FUNCTION_BLOCK SR_X
  VAR_INPUT S1 : BOOL; R : BOOL; END_VAR
  VAR_OUTPUT Q1 : BOOL; END_VAR
  Q1 := NOT R AND (S1 OR Q1);
END_FUNCTION_BLOCK
"""),
}
# The Logix timer of the dialect file against a plausible real one: ACC counts on the first enabled scan too.
FIRST_SCAN = re.compile(r"IF (\w+)_PREV AND NOT \1_DN THEN")


def with_helper(source: str, helper: str) -> str:
    first = re.search(r"^FUNCTION_BLOCK\s", source, flags=re.MULTILINE)
    return source[: first.start()] + helper + "\n(* st2fb:dut *)\n" + source[first.start() :]


def differences(source: str, edited: str, program_dir: Path, container: reference_run.Container) -> dict[str, int | str]:
    found: dict[str, int | str] = {}
    for path in scored_stimuli(program_dir):
        stimulus = json.loads(path.read_text(encoding="utf-8"))
        report = compare_traces(reference_run.run_reference(source, stimulus, container), reference_run.run_reference(edited, stimulus, container))
        if not report["equal"]:
            found[path.stem] = report["divergences"]
    return found


def run_all() -> list[dict[str, object]]:
    rows = []
    reference_run.ensure_image()
    with reference_run.Container() as container:
        for program_dir in program_dirs(REPO / "corpus_hard"):
            reference = program_dir / "reference.st"
            if not reference.exists():
                continue
            source = reference.read_text(encoding="utf-8")
            if program_dir.parent.name == "siemens_scl":
                for label, (pattern, replacement, helper) in VARIANTS.items():
                    if re.search(pattern, source):
                        rows.append({"program": program_dir.name, "reading": label, "differences": differences(source, with_helper(re.sub(pattern, replacement, source), helper), program_dir, container)})
            elif FIRST_SCAN.search(source):
                rows.append({"program": program_dir.name, "reading": "TONR counts on the first enabled scan", "differences": differences(source, FIRST_SCAN.sub(r"IF NOT \1_DN THEN", source), program_dir, container)})
    return rows


def main() -> int:
    rows = run_all()
    for row in rows:
        print(f"{row['program']:24} {row['reading']:48} {'same' if not row['differences'] else 'DIFFERS ' + json.dumps(row['differences'])}")
    siemens = [row for row in rows if row["program"].startswith("s") and row["differences"]]
    print(f"Siemens programs that depend on a listed reading: {len(siemens)}")
    return 1 if siemens else 0


if __name__ == "__main__":
    sys.exit(main())
