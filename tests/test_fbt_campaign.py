"""The FORTE mutation campaign, and the status sorting it relies on in st2fb.forte_eval."""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from st2fb import fbt, forte_eval, reference_run
from st2fb.mutate import fbt_mutants, select_mutants
from st2fb.translate import translate_source

REPO = Path(__file__).resolve().parent.parent
LATCH_DIR = REPO / "corpus/00_latch"
LATCH_SOURCE = (LATCH_DIR / "program.st").read_text()
LATCH = fbt.write_fbt(translate_source(LATCH_SOURCE))

spec = importlib.util.spec_from_file_location("fbt_mutation_campaign", REPO / "scripts/fbt_mutation_campaign.py")
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)


def docker_available() -> bool:
    return shutil.which("docker") is not None and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


class StatusesWithoutRunning(unittest.TestCase):
    STIMULUS = LATCH_DIR / "stimulus.json"

    def test_not_xml(self):
        outcome = forte_eval.evaluate("<FBType", self.STIMULUS, {})
        self.assertEqual(outcome.status, "parse_failed")

    def test_wrong_root(self):
        self.assertEqual(forte_eval.evaluate("<x/>", self.STIMULUS, {}).status, "parse_failed")

    def test_contract_break(self):
        broken = LATCH.replace('<With Var="COUNT"/>', "")
        outcome = forte_eval.evaluate(broken, self.STIMULUS, {})
        self.assertEqual(outcome.status, "plan_failed")
        self.assertIn("COUNT", outcome.detail)

    def test_trim_keeps_only_error_lines(self):
        log = "noise\nfb.cpp:1:2: error: bad thing\nmore noise\nFAILED: fb.o\nnoise\n"
        self.assertEqual(forte_eval.trim_compiler_output(log), "fb.cpp:1:2: error: bad thing\nFAILED: fb.o")
        self.assertEqual(forte_eval.trim_compiler_output("short log"), "short log")


class Reporting(unittest.TestCase):
    RESULTS = [
        {
            "program": "p",
            "scans": 9,
            "available": 20,
            "control": "equal",
            "mutants": [
                {"kind": "remove", "description": "d1", "outcome": "killed"},
                {"kind": "remove", "description": "d2", "outcome": "crashed"},
                {"kind": "constant", "description": "d3", "outcome": "timed_out"},
                {"kind": "constant", "description": "d4", "outcome": "survived", "heldout_outcome": "survived"},
                {"kind": "boundary", "description": "d5", "outcome": "survived"},
                {"kind": "operator", "description": "d6", "outcome": "compile_failed", "detail": "nope"},
            ],
        }
    ]

    def test_rate_counts_crashes_and_timeouts_as_detected_and_ignores_compile_failures(self):
        counts = campaign.tally(self.RESULTS[0]["mutants"])
        self.assertEqual(counts, {"killed": 1, "crashed": 1, "timed_out": 1, "survived": 2, "compile_failed": 1, "infra_failed": 0})
        self.assertEqual(campaign.rate(counts), "60.0%")

    def test_report_states_analysed_and_not_analysed_honestly(self):
        notes = {"survivors": {"p|d4": "Analysed: equivalent, reasoned and not proved."}}
        text = campaign.render_report(self.RESULTS, 5, 61499, notes, 1.0)
        self.assertIn("**Detected: 3 of 5 counted mutants (60.0%)**", text)
        self.assertIn("1 failed to compile and are not counted", text)
        self.assertIn("| p | `d4` | survived | Analysed: equivalent", text)
        self.assertIn("| p | `d5` | not run | Not analysed. |", text)
        self.assertIn("real FORTE", text)

    def test_jobs_cap(self):
        self.assertLessEqual(campaign.MAX_JOBS, 6)


class SelectionIsReproducible(unittest.TestCase):
    def test_same_seed_same_mutants(self):
        available = fbt_mutants(LATCH)
        first = select_mutants(available, 5, "61499:00_latch")
        second = select_mutants(fbt_mutants(LATCH), 5, "61499:00_latch")
        self.assertEqual([m.description for m in first], [m.description for m in second])
        self.assertEqual(len(first), 5)


@unittest.skipUnless(docker_available(), "needs Docker")
class OnRealForte(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st2fb-campaign-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def reference(self):
        return reference_run.run_reference(LATCH_SOURCE, json.loads((LATCH_DIR / "stimulus.json").read_text()))

    def test_equal_different_and_compile_failed(self):
        reference = self.reference()
        stimulus = LATCH_DIR / "stimulus.json"
        self.assertEqual(forte_eval.evaluate(LATCH, stimulus, reference).status, "equal")
        wrong = LATCH.replace("COUNT := COUNT + 1;", "COUNT := COUNT + 2;")
        outcome = forte_eval.evaluate(wrong, stimulus, reference)
        self.assertEqual(outcome.status, "different")
        self.assertEqual(outcome.report["first_divergence"]["output"], "COUNT")
        bad = LATCH.replace("COUNT := COUNT + 1;", "COUNT := UNKNOWN_NAME;")
        outcome = forte_eval.evaluate(bad, stimulus, reference)
        self.assertEqual(outcome.status, "compile_failed")
        self.assertIn("UNKNOWN_NAME", outcome.detail)

    def test_missing_cnf_times_out(self):
        reference = self.reference()
        no_cnf = LATCH.replace(' Output="CNF"', "")
        self.assertNotEqual(no_cnf, LATCH)
        outcome = forte_eval.evaluate(no_cnf, LATCH_DIR / "stimulus.json", reference, scan_timeout=1.0)
        self.assertEqual(outcome.status, "timed_out")
        self.assertIn("no CNF", outcome.detail)

    def test_campaign_on_one_program_deletes_mutant_binaries_and_keeps_the_control(self):
        with reference_run.Container() as container, ThreadPoolExecutor(max_workers=2) as pool:
            result = campaign.run_program(LATCH_DIR, 2, 61499, pool, container)
        self.assertEqual(result["control"], "equal")
        self.assertEqual(result["program"], "00_latch")
        self.assertEqual(len(result["mutants"]), 2)
        self.assertEqual(campaign.tally(result["mutants"])["killed"], 2)


if __name__ == "__main__":
    unittest.main()
