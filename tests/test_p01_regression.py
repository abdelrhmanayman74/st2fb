"""A zero preset on p01. Kept apart from the scored stimuli, which the published model run used."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROGRAM = REPO / "corpus_hard/public_st/p01_bistable_device"
CANDIDATE = (
    REPO
    / "results/hard_2026-11-07/siemens_scl+rockwell_st+public_st/candidates/claude-sonnet-5-5"
    / "p01_bistable_device/llm_repair_r0.fbt"
)


def run(*args: object) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", *map(str, args)], cwd=REPO, capture_output=True, text=True)


class ZeroPreset(unittest.TestCase):
    def test_saved_candidate_matches_and_a_known_survivor_is_caught(self):
        stimulus = PROGRAM / "regression_zero_preset.json"
        with tempfile.TemporaryDirectory() as temp:
            tmp = Path(temp)
            reference = tmp / "matiec.json"
            self.assertEqual(run("st2fb.reference_run", "--st", PROGRAM / "program.st", "--stimulus", stimulus, "--out", reference).returncode, 0)

            good = tmp / "good.json"
            self.assertEqual(run("st2fb.forte_run", "--fbt", CANDIDATE, "--stimulus", stimulus, "--out", good).returncode, 0)
            self.assertEqual(run("st2fb.compare", reference, good, "--out", tmp / "good_report.json").returncode, 0)

            self.assertEqual(run("st2fb.mutate", "fbt", CANDIDATE, "--count", 5, "--seed", 61499, "--out-dir", tmp / "mutants").returncode, 0)
            bad = tmp / "bad.json"
            self.assertEqual(run("st2fb.forte_run", "--fbt", tmp / "mutants/mutant_002.fbt", "--stimulus", stimulus, "--out", bad).returncode, 0)
            self.assertEqual(run("st2fb.compare", reference, bad, "--out", tmp / "bad_report.json").returncode, 1)
            self.assertFalse(json.loads((tmp / "bad_report.json").read_text())["equal"])


if __name__ == "__main__":
    unittest.main()
