"""The strict ecc_persistent metric, on hand-written fixtures, and its controls on real FORTE."""
import json
import re
import unittest
from pathlib import Path

from st2fb import forte_eval, reference_run
from st2fb.llm import benchmark, prompts
from st2fb.llm.ecc_metric import ecc_persistence
from st2fb.llm.engine import ecc_structure
from st2fb.translate import translate_source
from st2fb import fbt

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "ecc"
MACHINES = FIXTURES / "real_machines"
CANDIDATES = REPO / "results" / "benchmark_2026-11-06" / "candidates"


def run(name: str) -> dict:
    return ecc_persistence((FIXTURES / f"{name}.fbt").read_text(encoding="utf-8"))


class Positives(unittest.TestCase):
    def test_each_positive(self):
        for path in sorted(FIXTURES.glob("pos_*.fbt")):
            with self.subTest(path.stem):
                result = run(path.stem)
                self.assertTrue(result["ecc_persistent"], result["ecc_persistent_failures"])
                self.assertEqual(result["ecc_verdict"], "persistent")
                self.assertEqual(result["ecc_persistent_failures"], [])
                self.assertGreaterEqual(result["control_states"], 2)

    def test_exit_guards_on_a_variable_just_assigned_are_allowed(self):
        self.assertEqual(run("pos_exit_guard_assigned")["control_states"], 3)

    def test_prompt_example_meets_the_metric(self):
        result = ecc_persistence((prompts.PROMPT_DIR / "example_persistent_v1.fbt").read_text(encoding="utf-8"))
        self.assertTrue(result["ecc_persistent"], result["ecc_persistent_failures"])
        self.assertEqual(result["control_states"], 3)

    def test_a_real_lowered_timer_is_exempt(self):
        """The earlier version of this fixture was a two-line state variable that happened to be called X_STATE beside X_START_TIME, and the metric let it through
        on the name alone. That was the false accept fa3. The fixture now holds a real TON body, which is what the exemption is for."""
        text = (FIXTURES / "pos_shared_logic_timer_state.fbt").read_text(encoding="utf-8")
        self.assertIn("T_START_TIME + T#50ms <= NOW", text)
        self.assertEqual(ecc_persistence(text)["ecc_verdict"], "persistent")

    def test_a_lowered_timer_of_the_translator_is_exempt(self):
        """Every standard timer, as this project lowers it, in an algorithm shared by two control states."""
        for kind in ("TON", "TOF", "TP"):
            source = (
                f"FUNCTION_BLOCK F\nVAR_INPUT GO : BOOL; SCAN_IGNORED : BOOL; END_VAR\nVAR_OUTPUT SEQ : INT; END_VAR\nVAR T : {kind}; END_VAR\n"
                "T(IN := GO, PT := T#50ms);\nIF T.Q THEN\n  SEQ := 1;\nEND_IF;\nEND_FUNCTION_BLOCK\n"
            )
            wrapper = fbt.write_fbt(translate_source(source))
            persistent = (FIXTURES / "pos_two_positions.fbt").read_text(encoding="utf-8")
            body = re.search(r'<Algorithm Name="scan">\s*<ST><!\[CDATA\[(.*?)\]\]>', wrapper, flags=re.DOTALL).group(1)
            internal = re.search(r"<InternalVars>(.*?)</InternalVars>", wrapper, flags=re.DOTALL).group(1)
            text = persistent.replace("<InternalVars></InternalVars>", f"<InternalVars>{internal}</InternalVars>")
            text = text.replace('<ECAction Algorithm="step_a"', '<ECAction Algorithm="shared"/><ECAction Algorithm="step_a"').replace('<ECAction Algorithm="step_b"', '<ECAction Algorithm="shared"/><ECAction Algorithm="step_b"')
            text = text.replace('<Algorithm Name="step_a">', f'<Algorithm Name="shared"><ST><![CDATA[{body}]]></ST></Algorithm>\n<Algorithm Name="step_a">')
            with self.subTest(kind):
                self.assertEqual(ecc_persistence(text)["ecc_verdict"], "persistent", ecc_persistence(text))


class FalseRejects(unittest.TestCase):
    """The reviewer's real state machines, each of which equals matiec on real FORTE. The first version of the metric rejected all four."""

    EXPECTED = {"fr1_linear_no_return": 3, "fr2_retry_counter_guards": 3, "fr3_hysteresis_integer": 2, "fr4_shared_mode_branch": 2}

    def test_every_one_qualifies_now(self):
        for name, states in self.EXPECTED.items():
            with self.subTest(name):
                result = run(name)
                self.assertEqual(result["ecc_verdict"], "persistent", result)
                self.assertEqual(result["control_states"], states)

    def test_every_fixture_is_listed(self):
        self.assertEqual({path.stem for path in FIXTURES.glob("fr*.fbt")}, set(self.EXPECTED))


class FalseAccepts(unittest.TestCase):
    """The reviewer's hubs in disguise: two meaningless rest states and the position in a variable. Each equals matiec, and the first version of the metric accepted all seven."""

    EXPECTED = {
        "fa1_named_constants": "C3", "fa2_real_position": "C3", "fa3_timer_name_exempt": "C3", "fa4_bool_one_hot": "C3",
        "fa5_arithmetic_guard": "C3", "fa6_case_on_copy": "C4", "fa7_guard_on_copy": "C3",
    }

    def test_every_one_is_refused_for_the_expected_reason(self):
        for name, clause in self.EXPECTED.items():
            with self.subTest(name):
                result = run(name)
                self.assertIs(result["ecc_persistent"], False)
                self.assertTrue(any(reason.startswith(clause) for reason in result["ecc_persistent_failures"]), result["ecc_persistent_failures"])

    def test_every_fixture_is_listed(self):
        self.assertEqual({path.stem for path in FIXTURES.glob("fa*.fbt")}, set(self.EXPECTED))


class NeedsReading(unittest.TestCase):
    """Where a static check cannot tell, it says so rather than guessing."""

    EXPECTED = {"read_counter_position": "R1", "read_one_hot_booleans": "R2", "read_conditional_shared": "R3"}

    def test_each_one(self):
        for name, clause in self.EXPECTED.items():
            with self.subTest(name):
                result = run(name)
                self.assertEqual(result["ecc_verdict"], "needs_reading", result)
                self.assertIsNone(result["ecc_persistent"])
                self.assertEqual(result["ecc_persistent_failures"], [])
                self.assertTrue(any(reason.startswith(clause) for reason in result["ecc_needs_reading"]), result["ecc_needs_reading"])

    def test_every_fixture_is_listed(self):
        self.assertEqual({path.stem for path in FIXTURES.glob("read_*.fbt")}, set(self.EXPECTED))


class Negatives(unittest.TestCase):
    EXPECTED = {
        "neg_wrapper": "C1",
        "neg_hub_dispatch": "C1",
        "neg_first_scan_only": "C1",
        "neg_dead_end": "C1",
        "neg_common_hub": "C2",
        "neg_guard_table": "C3",
        "neg_guard_per_position": "C3",
        "neg_two_hop_copy": "C3",
        "neg_guard_reads_real_timer_state": "C3",
        "neg_algorithm_dispatch": "C4",
        "neg_if_chain_dispatch": "C4",
        "neg_case_on_expression": "C4",
        "neg_same_behaviour": "C5",
    }

    def test_every_negative_fixture_is_listed(self):
        self.assertEqual({path.stem for path in FIXTURES.glob("neg_*.fbt")}, set(self.EXPECTED))

    def test_each_negative_fails_for_the_expected_reason(self):
        for name, clause in self.EXPECTED.items():
            with self.subTest(name):
                result = run(name)
                self.assertIs(result["ecc_persistent"], False)
                self.assertTrue(any(reason.startswith(clause) for reason in result["ecc_persistent_failures"]), result["ecc_persistent_failures"])

    def test_restructured_is_not_enough(self):
        text = (FIXTURES / "neg_hub_dispatch.fbt").read_text(encoding="utf-8")
        self.assertTrue(ecc_structure(text)["restructured"])
        self.assertFalse(ecc_persistence(text)["ecc_persistent"])

    def test_translator_output_is_not_persistent(self):
        source = (REPO / "corpus/13_case_sequencer/program.st").read_text(encoding="utf-8")
        result = ecc_persistence(fbt.write_fbt(translate_source(source)))
        self.assertFalse(result["ecc_persistent"])
        self.assertEqual(result["control_states"], 1)

    def test_prompt_hub_example_is_not_persistent(self):
        self.assertFalse(ecc_persistence((prompts.PROMPT_DIR / "example.fbt").read_text(encoding="utf-8"))["ecc_persistent"])

    def test_unreadable(self):
        self.assertIsNone(ecc_persistence("not xml")["ecc_persistent"])
        self.assertEqual(ecc_persistence("not xml")["ecc_verdict"], "unreadable")

    def test_unreadable_guard_is_a_failure_with_a_reason(self):
        text = (FIXTURES / "pos_two_positions.fbt").read_text(encoding="utf-8").replace('Condition="[GO]"', 'Condition="[GO AND]"')
        result = ecc_persistence(text)
        self.assertIs(result["ecc_persistent"], False)
        self.assertIn("guard", result["ecc_persistent_failures"][0])

    def test_algorithm_read_after_a_definite_assignment_is_not_dispatch(self):
        text = (FIXTURES / "pos_two_positions.fbt").read_text(encoding="utf-8").replace(
            "SEQ := 0;\nIF GO THEN\n  SEQ := 1;\nEND_IF;",
            "SEQ := 1;\nCASE SEQ OF\n  1:\n    SEQ := 0;\n  2:\n    SEQ := 1;\nEND_CASE;",
        )
        self.assertTrue(ecc_persistence(text)["ecc_persistent"])

    def test_one_range_test_is_one_branch(self):
        """A shared output derived from a state number just assigned. Only a second test makes it dispatch."""
        base = (FIXTURES / "pos_two_positions.fbt").read_text(encoding="utf-8")
        one = "IF SEQ >= 1 AND SEQ <= 2 THEN\n  SEQ := 0;\nEND_IF;"
        two = "IF SEQ >= 1 THEN\n  SEQ := 0;\nELSIF SEQ <= 0 THEN\n  SEQ := 1;\nEND_IF;"
        for body, verdict in ((one, "persistent"), (two, "not_persistent")):
            text = base.replace('<ECAction Algorithm="step_a"', '<ECAction Algorithm="shared"/><ECAction Algorithm="step_a"').replace('<ECAction Algorithm="step_b"', '<ECAction Algorithm="shared"/><ECAction Algorithm="step_b"')
            text = text.replace('<Algorithm Name="step_a">', f'<Algorithm Name="shared"><ST><![CDATA[\n{body}\n]]></ST></Algorithm>\n<Algorithm Name="step_a">')
            with self.subTest(verdict):
                self.assertEqual(ecc_persistence(text)["ecc_verdict"], verdict)


class EarlierBenchmark(unittest.TestCase):
    def test_no_earlier_candidate_is_persistent_or_needs_reading(self):
        """The published run's `restructured` candidates are all hubs. This is what the new metric is for."""
        restructured = 0
        # Unreadable: five Sonnet candidates for 18_pump_station_rotation put InternalVars outside BasicFB,
        # which the parser now rejects by name. One of them passed the published run under the older parser.
        counts = {"persistent": 0, "needs_reading": 0, "not_persistent": 0, "unreadable": 0}
        for path in CANDIDATES.glob("*/*/*.fbt"):
            text = path.read_text(encoding="utf-8")
            counts[ecc_persistence(text)["ecc_verdict"]] += 1
            restructured += bool(ecc_structure(text)["restructured"])
        self.assertEqual(counts, {"persistent": 0, "needs_reading": 0, "not_persistent": 163, "unreadable": 5})
        self.assertEqual(restructured, 22)


class Controls(unittest.TestCase):
    """Runs on real FORTE: the form asked for is reachable, so a failing model is a real result."""

    @classmethod
    def setUpClass(cls):
        reference_run.ensure_image()

    def test_controls_meet_the_metric(self):
        for name in benchmark.ECC_PERSISTENT_PROGRAMS:
            with self.subTest(name):
                text = (REPO / "corpus_hard/ecc_persistent" / name / "control.fbt").read_text(encoding="utf-8")
                result = ecc_persistence(text)
                self.assertTrue(result["ecc_persistent"], result["ecc_persistent_failures"])

    def test_the_real_machines_equal_matiec(self):
        """So the false rejects were real solutions, and not just shapes the metric happens to like."""
        with reference_run.Container() as container:
            for name in FalseRejects.EXPECTED:
                source = (MACHINES / f"{name}.st").read_text(encoding="utf-8")
                path = MACHINES / f"{name}.json"
                trace = reference_run.run_reference(source, json.loads(path.read_text(encoding="utf-8")), container)
                with self.subTest(name):
                    self.assertEqual(forte_eval.evaluate((FIXTURES / f"{name}.fbt").read_text(encoding="utf-8"), path, trace).status, "equal")

    def test_prompt_example_equals_matiec(self):
        source = (prompts.PROMPT_DIR / "example_source.st").read_text(encoding="utf-8")
        text = (prompts.PROMPT_DIR / "example_persistent_v1.fbt").read_text(encoding="utf-8")
        scans = [
            {"OPEN_CMD": a, "AT_TOP": b}
            for a, b in [(False, False), (True, False), (False, False), (False, True), (False, False), (False, False), (True, True), (True, True), (False, False)]
        ]
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stimulus.json"
            stimulus = {"scan_ms": 10, "scans": scans}
            path.write_text(json.dumps(stimulus))
            outcome = forte_eval.evaluate(text, path, reference_run.run_reference(source, stimulus))
        self.assertEqual(outcome.status, "equal", outcome.report)

    def test_controls_equal_matiec_on_tuning_and_heldout(self):
        with reference_run.Container() as container:
            for name in benchmark.ECC_PERSISTENT_PROGRAMS:
                directory = REPO / "corpus" / name
                source = (directory / "program.st").read_text(encoding="utf-8")
                text = (REPO / "corpus_hard/ecc_persistent" / name / "control.fbt").read_text(encoding="utf-8")
                for file_name in ("stimulus.json", "heldout_stimulus.json"):
                    path = directory / file_name
                    trace = reference_run.run_reference(source, json.loads(path.read_text(encoding="utf-8")), container)
                    with self.subTest(name, stimulus=file_name):
                        self.assertEqual(forte_eval.evaluate(text, path, trace).status, "equal")


class FormPrompt(unittest.TestCase):
    def test_form_has_no_program_specific_text(self):
        text = (prompts.PROMPT_DIR / "form_ecc_persistent_v1.md").read_text(encoding="utf-8").lower()
        for name in benchmark.ECC_PERSISTENT_PROGRAMS:
            self.assertNotIn(name.lower(), text)
            self.assertNotIn(re.sub(r"^\d+_", "", name), text)


if __name__ == "__main__":
    unittest.main()
