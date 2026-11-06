"""The benchmark end to end with scripted fake responses, through real FORTE and real matiec.

Every response here is scripted. Nothing reaches a network, and every result is labelled fake. The fake
.fbt text comes from the deterministic translator and from the mutator, so the failures are real failures
of real FBs. Only the "model" is fake.
"""
import json
import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from st2fb import fbt
from st2fb.llm import benchmark, prompts
from st2fb.llm.client import FAKE, FakeClient, FakeReply
from st2fb.llm.budget import Ledger
from st2fb.mutate import fbt_mutants
from st2fb.translate import translate_source

REPO = Path(__file__).resolve().parent.parent
LATCH_SOURCE = (REPO / "corpus/00_latch/program.st").read_text()
LATCH = fbt.write_fbt(translate_source(LATCH_SOURCE))
# Removing PREV := Q makes COUNT run away on the first scan after Q has risen.
LATCH_WRONG = next(m.text for m in fbt_mutants(LATCH) if "removed 'PREV := Q;'" in m.description)
TOKEN_HEAVY = dict(input_tokens=5000, output_tokens=5000)


def docker_available() -> bool:
    return shutil.which("docker") is not None and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@unittest.skipUnless(docker_available(), "needs Docker")
class FakeScenarios(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st2fb-llm-e2e-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = self.tmp / "out"

    def weak_tuning_corpus(self) -> Path:
        """00_latch with a tuning stimulus of two scans: too short to expose LATCH_WRONG. Held-out is the real one."""
        corpus = self.tmp / "corpus"
        target = corpus / "00_latch"
        target.mkdir(parents=True)
        shutil.copy(REPO / "corpus/00_latch/program.st", target)
        shutil.copy(REPO / "corpus/00_latch/heldout_stimulus.json", target)
        tuning = json.loads((REPO / "corpus/00_latch/stimulus.json").read_text())
        tuning["scans"] = tuning["scans"][:2]
        (target / "stimulus.json").write_text(json.dumps(tuning))
        return corpus

    def run_benchmark(self, client, programs=("00_latch"), modes=("llm_repair",), repeats=1, budget=None, corpus=REPO / "corpus"):
        names = [programs] if isinstance(programs, str) else list(programs)
        cases = benchmark.load_cases(corpus, names)
        document, code = benchmark.run_benchmark(
            cases, list(modes), [("claude-sonnet-5-5", repeats)], client, budget, self.out, sleep=lambda s: None
        )
        self.document = document
        return code

    def row(self, mode="llm_repair", program="00_latch", repeat=0):
        return next(
            r for r in self.document["results"]
            if r["mode"] == mode and r["program"] == program and r["repeat"] == repeat
        )  # fmt: skip

    def test_correct_first_time(self):
        client = FakeClient([FakeReply(LATCH)])
        self.assertEqual(self.run_benchmark(client), 0)
        row = self.row()
        self.assertTrue(row["passed"])
        self.assertTrue(row["tuning_equal"])
        self.assertTrue(row["heldout_equal"])
        self.assertEqual(row["attempts"], 1)
        self.assertEqual((row["ecc_states"], row["working_states"], row["restructured"]), (2, 1, False))
        self.assertEqual(len(client.requests), 1)

    def test_malformed_xml_then_correct(self):
        client = FakeClient([FakeReply("<FBType Name='LATCH'><oops></FBType>"), FakeReply(LATCH)])
        self.run_benchmark(client)
        row = self.row()
        self.assertTrue(row["passed"])
        self.assertEqual(row["attempts"], 2)
        self.assertEqual(row["attempt_log"][0]["status"], "parse_failed")
        repair = client.requests[1].user
        self.assertIn("The file is not valid", repair)
        self.assertIn("not well-formed XML", repair)
        self.assertIn("<oops>", repair)

    def test_compile_error_then_correct(self):
        broken = LATCH.replace("COUNT := COUNT + 1;", "COUNT := NOT_DECLARED + 1;")
        self.assertNotEqual(broken, LATCH)
        client = FakeClient([FakeReply(broken), FakeReply(LATCH)])
        self.run_benchmark(client)
        self.assertTrue(self.row()["passed"])
        self.assertEqual(self.row()["attempt_log"][0]["status"], "compile_failed")
        self.assertIn("undeclared variable NOT_DECLARED", client.requests[1].user)

    def test_interface_break_then_correct(self):
        broken = LATCH.replace('<With Var="COUNT"/>', "")
        self.assertNotEqual(broken, LATCH)
        client = FakeClient([FakeReply(broken), FakeReply(LATCH)])
        self.run_benchmark(client)
        self.assertEqual(self.row()["attempt_log"][0]["status"], "plan_failed")
        self.assertIn("COUNT", client.requests[1].user)
        self.assertTrue(self.row()["passed"])

    def test_wrong_behaviour_on_tuning_then_correct(self):
        client = FakeClient([FakeReply(LATCH_WRONG), FakeReply(LATCH)])
        self.run_benchmark(client)
        row = self.row()
        self.assertTrue(row["passed"])
        self.assertEqual(row["attempts"], 2)
        self.assertEqual(row["attempt_log"][0]["status"], "different")
        repair = client.requests[1].user
        self.assertIn("First divergence: scan 2", repair)
        self.assertIn("output COUNT", repair)
        self.assertIn("expected 1, got 2", repair)
        self.assertIn('scan 2: {"S": false, "R": false}', repair)
        self.assertIn(LATCH_WRONG.strip(), repair)

    def test_passes_tuning_but_fails_held_out_scores_as_failed(self):
        client = FakeClient([FakeReply(LATCH_WRONG)])
        self.run_benchmark(client, corpus=self.weak_tuning_corpus())
        row = self.row()
        self.assertTrue(row["tuning_equal"])
        self.assertFalse(row["heldout_equal"])
        self.assertFalse(row["passed"])
        self.assertEqual(row["failure_category"], "heldout_different")
        # A held-out failure must not lead to a repair, which would leak held-out information.
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(len(client.requests), 1)
        aggregate = next(a for a in self.document["aggregate"] if a["mode"] == "llm_repair")
        self.assertEqual((aggregate["tuning_equal"], aggregate["heldout_equal"], aggregate["passed"]), (1, 0, 0))
        self.assertIsNone(aggregate["cost_per_pass_usd"])

    def test_real_corpus_mutant_that_only_held_out_catches(self):
        """Not a contrived stimulus: both files are the committed ones. See docs/FBT_MUTATION_RESULTS.md."""
        source = (REPO / "corpus/10_valve_feedback/program.st").read_text()
        base = fbt.write_fbt(translate_source(source))
        mutant = next(m.text for m in fbt_mutants(base, 10) if "removed 'OPENING_TIMER_STATE := 2;'" in m.description)
        client = FakeClient([FakeReply(mutant)])
        self.run_benchmark(client, programs="10_valve_feedback")
        row = self.row(program="10_valve_feedback")
        self.assertTrue(row["tuning_equal"])
        self.assertFalse(row["heldout_equal"])
        self.assertFalse(row["passed"])
        self.assertEqual(row["failure_category"], "heldout_different")
        self.assertEqual(len(client.requests), 1)

    def test_no_prompt_ever_contains_held_out_information(self):
        """Fail on tuning twice, so repair prompts exist, and look for values that only held-out has."""
        corpus = self.weak_tuning_corpus()
        always_wrong = LATCH.replace("COUNT := COUNT + 1;", "COUNT := COUNT + 7;")
        client = FakeClient([FakeReply(always_wrong), FakeReply(always_wrong), FakeReply(always_wrong)])
        tuning = json.loads((corpus / "00_latch/stimulus.json").read_text())
        tuning["scans"][1] = {"S": True, "R": False}
        (corpus / "00_latch/stimulus.json").write_text(json.dumps(tuning))
        self.run_benchmark(client, corpus=corpus)
        self.assertEqual(len(client.requests), 3)
        for request in client.requests:
            self.assertNotIn("heldout", request.user.lower())
            self.assertNotIn("heldout", request.system.lower())
            # The tuning stimulus here has 2 scans, so a higher scan number could only be held-out.
            for number in ("scan 2:", "scan 3:", "scan 50"):
                self.assertNotIn(number, request.user)

    def test_always_wrong_uses_all_attempts_and_fails(self):
        client = FakeClient([FakeReply(LATCH_WRONG)] * 3)
        self.run_benchmark(client)
        row = self.row()
        self.assertFalse(row["passed"])
        self.assertFalse(row["tuning_equal"])
        self.assertEqual(row["attempts"], 3)
        self.assertEqual(row["failure_category"], "tuning_different")
        self.assertEqual(len(client.requests), 3)

    def test_llm_only_gets_one_attempt(self):
        client = FakeClient([FakeReply(LATCH_WRONG)])
        self.run_benchmark(client, modes=("llm_only",))
        self.assertEqual(self.row("llm_only")["attempts"], 1)
        self.assertEqual(len(client.requests), 1)

    def test_refusal_is_not_retried(self):
        client = FakeClient([FakeReply("", stop_reason="refusal", refusal_category="cyber")])
        self.run_benchmark(client)
        row = self.row()
        self.assertFalse(row["passed"])
        self.assertEqual(row["failure_category"], "refusal")
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(row["attempt_log"][0]["refusal_category"], "cyber")
        self.assertGreater(row["cost_usd"], 0)  # A refusal is still recorded, and conservatively charged.
        self.assertIsNone(row["candidate_path"])

    def test_max_tokens_is_reported_and_not_evaluated(self):
        client = FakeClient([FakeReply(LATCH[:200], stop_reason="max_tokens")])
        self.run_benchmark(client)
        row = self.row()
        self.assertFalse(row["passed"])
        self.assertEqual(row["failure_category"], "max_tokens")
        self.assertIsNone(row["attempt_log"][0]["status"])
        self.assertEqual(len(client.requests), 1)

    def test_budget_cap_stops_the_run_midway(self):
        client = FakeClient(lambda request: FakeReply(LATCH, **TOKEN_HEAVY))
        # Each request costs 0.06 and is only sent if its worst case, about 0.37, still fits on top of
        # what was spent: 0 + 0.37 and 0.06 + 0.37 fit, and 0.12 + 0.37 does not.
        budget = 0.45
        code = self.run_benchmark(client, modes=("llm_only",), repeats=4, budget=budget)
        self.assertEqual(code, benchmark.EXIT_BUDGET)
        self.assertEqual(len(client.requests), 2)
        rows = [r for r in self.document["results"] if r["mode"] == "llm_only"]
        self.assertEqual([r["failure_category"] for r in rows], [None, None, "budget_stop", "not_run"])
        self.assertIn("budget", self.document["stopped"])
        ledger = Ledger(self.out / "ledger.jsonl", FAKE)
        self.assertLessEqual(ledger.spent_usd(), budget)
        aggregate = next(a for a in self.document["aggregate"] if a["mode"] == "llm_only")
        self.assertEqual((aggregate["runs"], aggregate["not_run"], aggregate["passed"]), (2, 2, 2))

    def test_budget_stop_during_a_repair_keeps_what_was_spent(self):
        client = FakeClient([FakeReply(LATCH_WRONG, **TOKEN_HEAVY)])
        self.run_benchmark(client, budget=0.40)
        row = self.row()
        self.assertEqual(row["failure_category"], "budget_stop")
        self.assertEqual(row["attempts"], 1)
        self.assertGreater(row["cost_usd"], 0)
        self.assertFalse(row["passed"])

    def test_a_ledger_from_an_earlier_run_counts_against_the_cap(self):
        ledger = Ledger(self.out / "ledger.jsonl", FAKE)
        ledger.settle(ledger.reserve(0.5, None, "earlier"), 0.5, [], None)
        client = FakeClient([FakeReply(LATCH)])
        code = self.run_benchmark(client, budget=0.5)
        self.assertEqual(code, benchmark.EXIT_BUDGET)
        self.assertEqual(client.requests, [])

    def test_cache_hit_on_rerun_spends_nothing(self):
        first = FakeClient([FakeReply(LATCH_WRONG), FakeReply(LATCH)])
        self.run_benchmark(first, budget=5.0)
        row = self.row()
        self.assertGreater(row["new_spend_usd"], 0)
        ledger_size = (self.out / "ledger.jsonl").read_text()

        second = FakeClient([])  # Would raise on any request.
        self.assertEqual(self.run_benchmark(second, budget=5.0), 0)
        again = self.row()
        self.assertEqual(second.requests, [])
        self.assertEqual(again["new_spend_usd"], 0.0)
        self.assertEqual(again["cached_calls"], 2)
        self.assertAlmostEqual(again["cost_usd"], row["cost_usd"])
        self.assertEqual(again["passed"], row["passed"])
        self.assertEqual((self.out / "ledger.jsonl").read_text(), ledger_size)

    def test_repeats_are_independent(self):
        client = FakeClient([FakeReply(LATCH), FakeReply(LATCH_WRONG)])
        self.run_benchmark(client, modes=("llm_only",), repeats=2)
        self.assertEqual(len(client.requests), 2)
        self.assertTrue(self.row("llm_only", repeat=0)["passed"])
        self.assertFalse(self.row("llm_only", repeat=1)["passed"])

    def test_modes_share_their_first_attempt_and_this_is_visible(self):
        client = FakeClient([FakeReply(LATCH)])
        self.run_benchmark(client, modes=("llm_only", "llm_repair"))
        self.assertEqual(len(client.requests), 1)
        only, repair = self.row("llm_only"), self.row("llm_repair")
        self.assertGreater(only["new_spend_usd"], 0)
        self.assertEqual(repair["new_spend_usd"], 0.0)
        self.assertEqual(repair["cached_calls"], 1)
        self.assertEqual(repair["cost_usd"], only["cost_usd"])
        self.assertIn("paired samples", (self.out / "benchmark.md").read_text())

    def test_baseline_is_in_the_report(self):
        self.run_benchmark(FakeClient([FakeReply(LATCH)]))
        row = self.row("baseline")
        self.assertTrue(row["passed"])
        self.assertEqual(row["model"], "deterministic-translator")
        self.assertEqual(row["cost_usd"], 0.0)

    def test_every_result_is_labelled_fake(self):
        self.run_benchmark(FakeClient([FakeReply(LATCH)]))
        document = json.loads((self.out / "benchmark.json").read_text())
        self.assertEqual(document["client"], "fake")
        self.assertIn("NOT results from any model", document["warning"])
        self.assertTrue(document["results"])
        for row in document["results"]:
            self.assertEqual(row["client"], "fake")
        self.assertIn("FAKE CLIENT", (self.out / "benchmark.md").read_text())
        for line in (self.out / "ledger.jsonl").read_text().splitlines():
            self.assertEqual(json.loads(line)["client"], "fake")
        for path in (self.out / "cache").iterdir():
            self.assertEqual(json.loads(path.read_text())["client"], "fake")

    def test_prompt_example_is_correct_and_restructured(self):
        """The example shown to the model must itself pass, or the prompt would teach a bug."""
        corpus = self.tmp / "example_corpus"
        target = corpus / "gate_cycle"
        target.mkdir(parents=True)
        shutil.copy(prompts.PROMPT_DIR / "example_source.st", target / "program.st")
        rng = random.Random(61499)
        for name, length in (("stimulus.json", 60), ("heldout_stimulus.json", 200)):
            scans = [{"OPEN_CMD": rng.random() < 0.4, "AT_TOP": rng.random() < 0.4} for _ in range(length)]
            (target / name).write_text(json.dumps({"scan_ms": 10, "scans": scans}))
        example = (prompts.PROMPT_DIR / "example.fbt").read_text()
        self.run_benchmark(FakeClient([FakeReply(example)]), programs="gate_cycle", corpus=corpus)
        row = self.row(program="gate_cycle")
        self.assertTrue(row["passed"], row)
        self.assertTrue(row["restructured"])
        self.assertEqual((row["ecc_states"], row["working_states"]), (6, 5))
        self.assertTrue(row["source_has_case"])
        # The deterministic baseline passes too, and is a wrapper, which is the comparison being made.
        base = self.row("baseline", program="gate_cycle")
        self.assertTrue(base["passed"])
        self.assertFalse(base["restructured"])


if __name__ == "__main__":
    unittest.main()
