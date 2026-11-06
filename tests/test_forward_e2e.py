"""End-to-end tests: real FORTE in Docker. Skipped when Docker is unavailable."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def run_module(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", *args], cwd=REPO, capture_output=True, text=True)


@unittest.skipUnless(docker_available(), "needs Docker")
class ForteRunTests(unittest.TestCase):
    def setUp(self):
        # Under build/ so that the bind mounts work with any Docker file sharing setup.
        (REPO / "build").mkdir(exist_ok=True)
        self.tmp = Path(tempfile.mkdtemp(prefix="test-", dir=REPO / "build"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def forte_run(self, fbt_path: Path, stimulus: Path, name: str = "forte.json", *extra: str) -> tuple[subprocess.CompletedProcess, Path]:
        out = self.tmp / name
        return run_module("st2fb.forte_run", "--fbt", str(fbt_path), "--stimulus", str(stimulus), "--out", str(out), *extra), out

    def write_stimulus(self, scans: list[dict], scan_ms: int = 10) -> Path:
        path = self.tmp / "stimulus.json"
        path.write_text(json.dumps({"scan_ms": scan_ms, "scans": scans}))
        return path

    def translate(self, source: str) -> Path:
        st = self.tmp / "program.st"
        st.write_text(source)
        out = self.tmp / "out.fbt"
        result = run_module("st2fb.translate", str(st), "--out", str(out))
        self.assertEqual(result.returncode, 0, result.stderr)
        return out

    def test_latch_translate_run_and_determinism(self):
        fbt_path = self.tmp / "LATCH.fbt"
        result = run_module("st2fb.translate", "corpus/00_latch/program.st", "--out", str(fbt_path))
        self.assertEqual(result.returncode, 0, result.stderr)

        stimulus = REPO / "corpus/00_latch/stimulus.json"
        first, first_out = self.forte_run(fbt_path, stimulus, "first.json")
        self.assertEqual(first.returncode, 0, first.stderr)
        second, second_out = self.forte_run(fbt_path, stimulus, "second.json")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first_out.read_bytes(), second_out.read_bytes())

        trace = json.loads(first_out.read_text())
        self.assertEqual(trace["source"], "forte")
        self.assertEqual(trace["scan_ms"], 10)
        self.assertEqual(trace["outputs"], ["Q", "COUNT"])
        # Worked out by hand from program.st and stimulus.json.
        self.assertEqual(trace["scans"], [
            {"t_ms": 0, "Q": False, "COUNT": 0},
            {"t_ms": 10, "Q": True, "COUNT": 1},
            {"t_ms": 20, "Q": True, "COUNT": 1},
            {"t_ms": 30, "Q": False, "COUNT": 1},
            {"t_ms": 40, "Q": False, "COUNT": 1},
            {"t_ms": 50, "Q": True, "COUNT": 2},
            {"t_ms": 60, "Q": True, "COUNT": 2},
        ])

    def test_hand_written_multi_state_fb(self):
        result, out = self.forte_run(FIXTURES / "multistate.fbt", FIXTURES / "multistate_stimulus.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        trace = json.loads(out.read_text())
        self.assertEqual(trace["outputs"], ["VALVE", "CYCLES", "TOTAL", "BATCH", "RATIO", "ELAPSED"])

        def record(t_ms, valve, cycles, total, batch, ratio, elapsed):
            return {"t_ms": t_ms, "VALVE": valve, "CYCLES": cycles, "TOTAL": total, "BATCH": batch,
                    "RATIO": ratio, "ELAPSED": elapsed}

        # Worked out by hand from the ECC. The t_ms=60 scan passes FULL then RESET and emits CNF
        # twice; the outputs are the values after RESET, and t_ms=70 is not shifted by the extra reply.
        self.assertEqual(trace["scans"], [
            record(0, False, 0, 100, 0, 0.0, 0),    # OFF
            record(10, True, 0, 101, 0, 0.5, 10),   # FILL, CASE label 0
            record(20, True, 0, 111, 0, 1.0, 20),   # FILL, CASE list 1, 2
            record(30, True, 0, 211, 0, 1.5, 30),   # FILL, CASE range 3..5
            record(40, True, 0, 210, 0, 2.0, 40),   # FILL, CASE ELSE
            record(50, False, 1, 210, 4, 2.0, 40),  # FULL: FOR adds 6, WHILE trims to 4
            record(60, False, 0, 210, 4, 2.0, 0),   # FULL then RESET through [CYCLES >= 2]
            record(70, True, 0, 220, 4, 2.5, 10),   # FILL
        ])

    def test_lowered_ton_on_forte(self):
        fbt_path = self.translate("""
            FUNCTION_BLOCK DELAY
            VAR_INPUT GO : BOOL; END_VAR
            VAR_OUTPUT DONE : BOOL; SO_FAR : TIME; END_VAR
            VAR T1 : TON; END_VAR
            T1(IN := GO, PT := T#30ms);
            DONE := T1.Q;
            SO_FAR := T1.ET;
            END_FUNCTION_BLOCK
        """)
        go = [False, True, True, True, True, True, False]
        result, out = self.forte_run(fbt_path, self.write_stimulus([{"GO": g} for g in go]))
        self.assertEqual(result.returncode, 0, result.stderr)
        # SCAN_DT is not in the stimulus: forte_run sets it to scan_ms.
        self.assertEqual(
            [(s["DONE"], s["SO_FAR"]) for s in json.loads(out.read_text())["scans"]],
            [(False, 0), (False, 0), (False, 10), (False, 20), (True, 30), (True, 30), (False, 0)],
        )

    def test_corner_cases_match_recorded_matiec_trace(self):
        fbt_path = self.translate((FIXTURES / "semantics.st").read_text())
        result, out = self.forte_run(fbt_path, FIXTURES / "semantics_stimulus.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = json.loads((FIXTURES / "semantics_matiec.json").read_text())
        actual = json.loads(out.read_text())
        self.assertEqual(actual["outputs"], expected["outputs"])
        self.assertEqual(len(actual["scans"]), len(expected["scans"]))
        for want, got in zip(expected["scans"], actual["scans"]):
            for key, value in want.items():
                if isinstance(value, float):
                    self.assertLessEqual(abs(got[key] - value), 1e-5 * abs(value), (want["t_ms"], key))
                else:
                    self.assertEqual(got[key], value, (want["t_ms"], key))

    def test_missing_cnf_fails_with_a_clear_message(self):
        fbt_path = self.tmp / "silent.fbt"
        fbt_path.write_text((REPO / "corpus/00_latch/expected.fbt").read_text().replace(
            'Algorithm="scan" Output="CNF"', 'Algorithm="scan"'))
        out = self.tmp / "forte.json"
        out.write_text("stale")
        result, _ = self.forte_run(fbt_path, REPO / "corpus/00_latch/stimulus.json", "forte.json", "--scan-timeout", "1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("scan 0: no CNF", result.stderr)
        self.assertFalse(out.exists())

    def test_infinite_loop_fails_instead_of_hanging(self):
        fbt_path = self.translate("""
            FUNCTION_BLOCK SPIN
            VAR_INPUT GO : BOOL; END_VAR
            VAR_OUTPUT Q : BOOL; END_VAR
            WHILE GO DO Q := TRUE; END_WHILE;
            END_FUNCTION_BLOCK
        """)
        result, _ = self.forte_run(fbt_path, self.write_stimulus([{"GO": True}]), "forte.json", "--scan-timeout", "1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no CNF", result.stderr)

    def test_stimulus_errors_need_no_docker_run(self):
        for scans, message in (
            ([{"S": True}], "missing inputs"),
            ([{"S": True, "R": False, "X": 1}], "unknown inputs"),
            ([{"S": 1, "R": False}], "expected a JSON bool"),
        ):
            result, _ = self.forte_run(REPO / "corpus/00_latch/expected.fbt", self.write_stimulus(scans))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stderr)


if __name__ == "__main__":
    unittest.main()
