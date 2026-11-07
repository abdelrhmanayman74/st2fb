"""corpus_hard/ and what was added for it: dialect prompts, baseline status, report format, protected results."""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import itertools
import json
import re
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from st2fb import compare, fbt, forte_eval, mutate, reference_run
from st2fb.llm import benchmark, hard_check, manifest, prompts
from st2fb.llm.cache import cache_key
from st2fb.llm.client import LIVE, FakeClient, FakeReply, LlmRequest
from st2fb.llm.config import DEFAULT_EFFORT, DEFAULT_MAX_TOKENS, LlmConfig
from st2fb.translate import translate_source

REPO = Path(__file__).resolve().parent.parent
HARD = REPO / "corpus_hard"
SETS = hard_check.SETS
ACCEPTED_BY_BASELINE = {"p03_alpha_beta_filter", "p04_debounce_bool"}
PASS_FRONTEND = ACCEPTED_BY_BASELINE | {
    "p01_bistable_device", "s01_conveyor_starter", "s02_analog_input", "s03_valve_monitor", "s04_batch_steps", "s06_status_word", "s07_heater_pi", "s08_packaging_counter",
    "r01_motor_aoi", "r02_fill_retry_aoi", "r03_sequence_aoi", "r04_alarm_word_aoi",
}
EARLIER = REPO / "results" / "benchmark_2026-11-06"
STIMULI = ("stimulus.json", "heldout_stimulus.json", "heldout_stimulus_2.json", "pairing_stimulus.json")


def all_cases() -> list[benchmark.Case]:
    return [case for name in SETS for case in benchmark.load_set(HARD / name)]


def load_generator():
    spec = importlib.util.spec_from_file_location("hard_generate_stimuli", HARD / "generate_stimuli.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Contents(unittest.TestCase):
    def test_counts(self):
        counts = {name: len(benchmark.load_set(HARD / name)) for name in SETS}
        self.assertEqual(counts["unsupported_st"], 6)
        self.assertEqual(counts["siemens_scl"], 8)
        self.assertEqual(counts["rockwell_st"], 4)
        self.assertEqual(counts["stress"], 1)
        self.assertEqual(counts["public_st"], 4)

    def test_baseline_rejects_what_this_corpus_says_it_rejects(self):
        for case in all_cases():
            with self.subTest(case.name):
                if case.name in ACCEPTED_BY_BASELINE:
                    translate_source(case.source)
                else:
                    with self.assertRaises(ValueError):
                        translate_source(case.source)

    def test_paired_programs_have_a_separate_oracle(self):
        for case in all_cases():
            with self.subTest(case.name):
                if case.set_name in ("siemens_scl", "rockwell_st"):
                    self.assertIsNotNone(case.oracle)
                    self.assertNotEqual(case.source, case.oracle)
                else:
                    self.assertIsNone(case.oracle)

    def test_stress_says_who_wrote_it_where_a_model_does_not_read_it(self):
        text = (HARD / "stress/x01_pump_station/README.md").read_text(encoding="utf-8")
        self.assertIn("AI tooling", text)
        self.assertNotIn("AI tooling", (HARD / "stress/x01_pump_station/program.st").read_text(encoding="utf-8"))

    def test_no_source_carries_a_hint(self):
        """A source reaches the model, so what it was written to test, and how a tricky instruction behaves, stay out of it."""
        for case in all_cases():
            with self.subTest(case.name):
                for phrase in ("Out of scope", "translator", "AI tooling", "leaves only", "half goes", "even neighbour", "half to even", "NOTICE.md", "README"):
                    self.assertNotIn(phrase, case.source)

    def test_vendor_sources_avoid_the_disputed_instructions(self):
        """SCL's F_TRIG, SR and RS, and CTU past PV, are written out as IFs, so that no result turns on which reading of them is right. See docs/HARD_CORPUS.md."""
        for case in benchmark.load_set(HARD / "siemens_scl"):
            with self.subTest(case.name):
                for word in ("F_TRIG", ": SR;", ": RS;"):
                    self.assertNotIn(word, case.source)
                    self.assertNotIn(word, case.oracle)
        for name in ("s03_valve_monitor", "s08_packaging_counter"):
            case = next(c for c in benchmark.load_set(HARD / "siemens_scl") if c.name == name)
            self.assertNotIn("CTU", case.source)
            self.assertNotIn("CTU", case.oracle)

    def test_public_programs_keep_their_notices(self):
        for directory in sorted((HARD / "public_st").glob("p*")):
            with self.subTest(directory.name):
                self.assertTrue((directory / "LICENSE").read_text(encoding="utf-8").strip())
                notice = (directory / "NOTICE.md").read_text(encoding="utf-8")
                self.assertRegex(notice, r"https://github\.com/")
                self.assertRegex(notice, r"[0-9a-f]{40}")
                self.assertIn("Copyright", (directory / "program.st").read_text(encoding="utf-8"))


class Stimuli(unittest.TestCase):
    def test_regenerating_gives_the_files_on_disk(self):
        generator = load_generator()
        for key in sorted(generator.SCENARIOS):
            built = generator.build(key)
            for file_name, stimulus in built.items():
                with self.subTest(key, file=file_name):
                    self.assertEqual(generator.render(stimulus), (HARD / key / file_name).read_text(encoding="utf-8"))

    def test_every_program_has_four_different_stimuli_that_fit_its_interface(self):
        for case in all_cases():
            directory = case.tuning_path.parent
            interface = reference_run.scan_interface(case.oracle_source)
            names = {var.name for var in interface.inputs}
            loaded = {name: json.loads((directory / name).read_text(encoding="utf-8")) for name in STIMULI}
            with self.subTest(case.name):
                self.assertEqual(case.heldout_paths, (directory / "heldout_stimulus.json", directory / "heldout_stimulus_2.json"))
                for one, other in itertools.combinations(STIMULI, 2):
                    self.assertNotEqual(loaded[one]["scans"], loaded[other]["scans"])
                for name in ("heldout_stimulus.json", "heldout_stimulus_2.json"):
                    self.assertGreater(len(loaded[name]["scans"]), len(loaded["stimulus.json"]["scans"]))
                for stimulus in loaded.values():
                    self.assertEqual(set(stimulus["scans"][0]), names)

    def test_a_second_held_out_file_runs_at_another_period(self):
        """A migration that hard-codes the scan period has to fail somewhere, and a stimulus file holds one period."""
        for case in all_cases():
            directory = case.tuning_path.parent
            periods = {name: json.loads((directory / name).read_text(encoding="utf-8"))["scan_ms"] for name in STIMULI}
            with self.subTest(case.name):
                self.assertEqual(periods["heldout_stimulus.json"], periods["stimulus.json"])
                self.assertEqual(periods["pairing_stimulus.json"], periods["stimulus.json"])
                self.assertNotEqual(periods["heldout_stimulus_2.json"], periods["stimulus.json"])

    def test_task_period_input_is_the_scan_period_of_each_file(self):
        for case in benchmark.load_set(HARD / "rockwell_st"):
            for name in STIMULI:
                stimulus = json.loads((case.tuning_path.parent / name).read_text(encoding="utf-8"))
                with self.subTest(case.name, file=name):
                    self.assertEqual({scan["TaskPeriodMs"] for scan in stimulus["scans"]}, {stimulus["scan_ms"]})

    def test_no_scored_file_shares_more_than_one_first_scan_with_tuning(self):
        for case in all_cases():
            tuning = json.loads(case.tuning_path.read_text(encoding="utf-8"))["scans"]
            for path in case.heldout_paths:
                scans = json.loads(path.read_text(encoding="utf-8"))["scans"]
                shared = next((index for index, (a, b) in enumerate(zip(tuning, scans)) if a != b), len(scans))
                with self.subTest(case.name, file=path.name):
                    self.assertEqual(shared, 0, "each held-out file already differs from tuning on scan 0")

    def test_inputs_named_by_the_review_vary_and_tuning_holds_one_value(self):
        """Tuning holds one value of each of these, so that a value frozen from tuning fails on held-out."""
        named = {
            "s02_analog_input": ("i_alarmDelay",),
            "s08_packaging_counter": ("i_maxSpeed",),
            "r02_fill_retry_aoi": ("StartPct", "StopPct"),
            "u01_sensor_voting": ("BAND", "SPAN", "DISAGREE_DELAY"),
            "x01_pump_station": ("LEVEL_STOP", "LEVEL_1", "LEVEL_2", "LEVEL_3", "RETRY_DELAY", "STAGE_DELAY", "ROTATE_TIME"),
            "r01_motor_aoi": ("TaskPeriodMs",), "r03_sequence_aoi": ("TaskPeriodMs",), "r04_alarm_word_aoi": ("TaskPeriodMs",),
        }
        cases = {case.name: case for case in all_cases()}
        for program, inputs in named.items():
            case = cases[program]
            tuning = json.loads(case.tuning_path.read_text(encoding="utf-8"))["scans"]
            held = [scan for path in case.heldout_paths for scan in json.loads(path.read_text(encoding="utf-8"))["scans"]]
            for name in inputs:
                with self.subTest(program, input=name):
                    self.assertEqual(len({scan[name] for scan in tuning}), 1)
                    self.assertTrue({scan[name] for scan in held} - {scan[name] for scan in tuning})

    def test_new_status_word_bits_are_only_on_held_out(self):
        case = next(c for c in benchmark.load_set(HARD / "siemens_scl") if c.name == "s06_status_word")
        tuning = {scan["i_controlWord"] for scan in json.loads(case.tuning_path.read_text(encoding="utf-8"))["scans"]}
        held = {scan["i_controlWord"] for path in case.heldout_paths for scan in json.loads(path.read_text(encoding="utf-8"))["scans"]}
        self.assertTrue({384, 512} <= held)
        self.assertFalse({384, 512} & tuning)

    def test_audit_finds_nothing(self):
        spec = importlib.util.spec_from_file_location("audit_stimuli", REPO / "scripts/audit_stimuli.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(), 0)

    def test_real_inputs_are_exact_in_binary(self):
        """A REAL that binary cannot hold would make a stimulus depend on how decimal text is rounded."""
        for case in all_cases():
            interface = reference_run.scan_interface(case.oracle_source)
            reals = [var.name for var in interface.inputs if var.type == "REAL"]
            for path in (case.tuning_path, *case.heldout_paths):
                for scan in json.loads(path.read_text(encoding="utf-8"))["scans"]:
                    for name in reals:
                        self.assertEqual(scan[name] * 16, int(scan[name] * 16), (case.name, path.name, name))


class HardCodedPeriod(unittest.TestCase):
    """A migration that freezes the scan period passes on tuning, and has to fail on the second held-out file."""

    @classmethod
    def setUpClass(cls):
        reference_run.ensure_image()

    def test_scan_dt_removed_on_real_forte(self):
        case = next(c for c in benchmark.load_set(HARD / "siemens_scl") if c.name == "s01_conveyor_starter")
        good = fbt.write_fbt(translate_source(case.oracle))
        wrong = good.replace("ST2FB_NOW := ST2FB_NOW + SCAN_DT;", "ST2FB_NOW := ST2FB_NOW + T#10ms;")
        wrong = re.sub(r'<With Var="SCAN_DT"\s*/>', "", wrong)
        wrong = re.sub(r'<VarDeclaration Name="SCAN_DT"[^>]*/>', "", wrong)
        self.assertNotIn("SCAN_DT", wrong)
        with reference_run.Container() as container:
            references = benchmark.load_references(case, container)
        self.assertEqual(forte_eval.evaluate(wrong, case.tuning_path, references["tuning"]).status, "equal")
        statuses = [forte_eval.evaluate(wrong, path, trace).status for path, trace in zip(case.heldout_paths, references["heldout_all"])]
        self.assertEqual(statuses, ["equal", "different"])

    def test_task_period_replaced_on_every_logix_program(self):
        with reference_run.Container() as container:
            for case in benchmark.load_set(HARD / "rockwell_st"):
                wrong = case.oracle.replace("+ TaskPeriodMs", "+ 10")
                self.assertNotEqual(wrong, case.oracle)
                for path, should_differ in ((case.tuning_path, False), (case.heldout_paths[0], False), (case.heldout_paths[1], True)):
                    stimulus = json.loads(path.read_text(encoding="utf-8"))
                    report = compare.compare_traces(reference_run.run_reference(case.oracle, stimulus, container), reference_run.run_reference(wrong, stimulus, container))
                    with self.subTest(case.name, file=path.name):
                        self.assertEqual(report["equal"], not should_differ)

    def test_totaliser_period_replaced(self):
        case = next(c for c in benchmark.load_set(HARD / "rockwell_st") if c.name == "r02_fill_retry_aoi")
        wrong = case.oracle.replace("DINT_TO_REAL(TaskPeriodMs)", "10.0")
        self.assertNotEqual(wrong, case.oracle)
        stimulus = json.loads(case.heldout_paths[1].read_text(encoding="utf-8"))
        self.assertFalse(compare.compare_traces(reference_run.run_reference(case.oracle, stimulus), reference_run.run_reference(wrong, stimulus))["equal"])


class DirectedStress(unittest.TestCase):
    """What the review found the stress program's stimuli could not see."""

    def test_directed_mutants_are_killed_on_tuning_and_held_out(self):
        reference_run.ensure_image()
        case = next(iter(benchmark.load_set(HARD / "stress")))
        for label, old, new in (
            ("interlock guard 4 to 3", "IF NOT PERMIT AND STATE <> 4 THEN", "IF NOT PERMIT AND STATE <> 3 THEN"),
            ("interlock guard 4 to 5", "IF NOT PERMIT AND STATE <> 4 THEN", "IF NOT PERMIT AND STATE <> 5 THEN"),
            ("LEVEL_2 >= to >", "ELSIF LEVEL >= LEVEL_2 THEN", "ELSIF LEVEL > LEVEL_2 THEN"),
        ):
            wrong = case.source.replace(old, new)
            self.assertNotEqual(wrong, case.source)
            with reference_run.Container() as container:
                for path in (case.tuning_path, *case.heldout_paths):
                    stimulus = json.loads(path.read_text(encoding="utf-8"))
                    with self.subTest(label, file=path.name):
                        self.assertFalse(compare.compare_traces(reference_run.run_reference(case.source, stimulus, container), reference_run.run_reference(wrong, stimulus, container))["equal"])

    def test_every_pump_reaches_every_state(self):
        reference_run.ensure_image()
        spec = importlib.util.spec_from_file_location("x01_state_reach", REPO / "scripts/x01_state_reach.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(), 0)


class VendorReadings(unittest.TestCase):
    def test_no_siemens_result_depends_on_a_listed_reading(self):
        spec = importlib.util.spec_from_file_location("check_vendor_readings", REPO / "scripts/check_vendor_readings.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        for row in module.run_all():
            if row["program"].startswith("s"):
                with self.subTest(row["program"], reading=row["reading"]):
                    self.assertEqual(row["differences"], {})


class ManifestCheck(unittest.TestCase):
    def test_a_real_run_needs_a_pass_on_these_files(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / "hard_check.json"
            with self.assertRaisesRegex(manifest.NotChecked, "does not exist"):
                manifest.require_passed(record)
            record.write_text(json.dumps({"passed": False, "manifest": None}))
            with self.assertRaisesRegex(manifest.NotChecked, "did not pass"):
                manifest.require_passed(record)
            record.write_text(json.dumps({"passed": True, "manifest": "0" * 64}))
            with self.assertRaisesRegex(manifest.NotChecked, "changed since"):
                manifest.require_passed(record)
            record.write_text(json.dumps({"passed": True, "manifest": manifest.compute()}))
            manifest.require_passed(record)

    def test_every_scored_and_shown_file_is_covered(self):
        covered = set(manifest.files())
        for case in all_cases():
            for path in (case.tuning_path, *case.heldout_paths):
                self.assertIn(path, covered)
        self.assertIn(prompts.PROMPT_DIR / "dialect_siemens_scl_v1.md", covered)
        self.assertIn(HARD / "ecc_persistent/06_star_delta/control.fbt", covered)
        self.assertEqual(manifest.ECC_PROGRAMS, benchmark.ECC_PERSISTENT_PROGRAMS)

    def test_the_cli_refuses_a_real_run_and_a_live_client_is_refused_too(self):
        original = manifest.RECORD
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "none.json"
            with mock.patch.object(manifest.require_passed, "__defaults__", (missing,)):
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    code = benchmark.main(["--corpus-dir", str(HARD / "stress"), "--out-dir", directory, "--modes", "llm_only"])
                self.assertEqual(code, benchmark.EXIT_NOT_CHECKED)
                self.assertIn("hard_check", err.getvalue())

                class LiveShaped:
                    kind = LIVE

                with self.assertRaises(manifest.NotChecked):
                    benchmark.run_benchmark([], [], [], LiveShaped(), 1.0, Path(directory), hard={"sets": [], "form": None})
        self.assertEqual(manifest.RECORD, original)


class PromptRules(unittest.TestCase):
    NEW_FILES = ["addendum_hard_v1.md", "generate_dialect_v1.md", "form_ecc_persistent_v1.md"] + [file for _, file in prompts.DIALECTS.values()]
    # A convention of the dialect, named on purpose, since every Logix program here has this input. The others are
    # ordinary English words that public_st happens to use as names.
    GENERIC = {"TaskPeriodMs", "output", "Output"}

    def test_no_program_specific_text_in_any_new_prompt(self):
        names = set()
        for case in all_cases():
            interface = reference_run.scan_interface(case.oracle_source)
            names.add(interface.fb_name)
            names.add(case.name)
            names |= {var.name for var in interface.inputs + interface.outputs if len(var.name) > 3}
        for file_name in self.NEW_FILES:
            words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", (prompts.PROMPT_DIR / file_name).read_text(encoding="utf-8")))
            with self.subTest(file_name):
                self.assertEqual(sorted((words & names) - self.GENERIC), [])

    def test_default_profile_is_exactly_the_old_prompt(self):
        expected = prompts._fill(
            prompts._read("system.md"),
            STD_FB_SEMANTICS=prompts._read("std_fb_semantics.md"),
            EXAMPLE_SOURCE=prompts._read("example_source.st"),
            EXAMPLE_FBT=prompts._read("example.fbt"),
        )
        self.assertEqual(prompts.system_prompt(), expected)
        self.assertEqual(prompts.generate_prompt("X"), prompts._fill(prompts._read("generate.md"), SOURCE="X"))

    def test_old_prompt_files_have_not_changed(self):
        """sha256 of the prompts behind the published benchmark. A change here would change its cache keys."""
        expected = {
            "system.md": "c21220bf5376b471bcbf5a6975ea43d1d9e8af547e29f76a4a81fc245b29ba9d",
            "generate.md": "1c3fa785a32ded6e6b6920b8d95a6fc1bd54270a6347f69625440caa7c167fd4",
            "repair.md": "3a867210695f639308442ddefa1271705927452341399de8e10a1cfdcb281825",
            "std_fb_semantics.md": "4cdae3c03ae7f380b321b24547fd14427ff0240a710a6cba4615d0cd53d74ecf",
            "example_source.st": "9c755c915cdcdd45acfef13644c05d902987a45ce1b68e284ef235c28aa0984d",
            "example.fbt": "9bac5788091240d58764c810573aff7a46fec76edfa23e0eff3361d3e0366014",
        }
        for name, digest in expected.items():
            with self.subTest(name):
                self.assertEqual(hashlib.sha256((prompts.PROMPT_DIR / name).read_bytes()).hexdigest(), digest)

    def test_dialect_prompt_carries_the_dialect(self):
        profile = prompts.PromptProfile("siemens_scl")
        self.assertIn("Siemens SCL", prompts.system_prompt(profile))
        self.assertIn("Siemens SCL", prompts.generate_prompt("x", profile))
        self.assertIn("TON_TIME", prompts.system_prompt(profile))
        self.assertNotIn("TONR", prompts.system_prompt(profile))
        self.assertIn("TONR", prompts.system_prompt(prompts.PromptProfile("rockwell_logix")))

    def test_form_replaces_structure_only_when_asked(self):
        self.assertNotIn("Required form", prompts.system_prompt())
        self.assertIn("Required form", prompts.system_prompt(prompts.PromptProfile(None, "ecc_persistent")))

    def test_unknown_dialect_and_form_are_refused(self):
        with self.assertRaises(ValueError):
            prompts.PromptProfile("ladder")
        with self.assertRaises(ValueError):
            prompts.PromptProfile(None, "pretty")


class EarlierBenchmarkStillReproduces(unittest.TestCase):
    def test_report_renders_byte_for_byte(self):
        document = json.loads((EARLIER / "benchmark.json").read_text(encoding="utf-8"))
        self.assertEqual(benchmark.render_markdown(document), (EARLIER / "benchmark.md").read_text(encoding="utf-8"))

    def test_cache_keys_still_find_the_paid_responses(self):
        """No request is made. Only the keys are computed, and looked for in the cache a live run left behind.

        The published run used --no-fallbacks, which is part of the key.
        """
        cache = REPO / "build" / "llm" / "cache"
        if not cache.is_dir():
            self.skipTest("build/llm/cache is not in git, and exists only after a live run")
        found = checked = 0
        for case in benchmark.load_cases(REPO / "corpus", ["all"]):
            for model, repeats in (("claude-sonnet-5-5", 3), ("claude-opus-5-5", 1)):
                config = LlmConfig(model, DEFAULT_EFFORT, DEFAULT_MAX_TOKENS, False)
                request = LlmRequest(system=prompts.system_prompt(), user=prompts.generate_prompt(case.source), config=config, tag="")
                for repeat in range(repeats):
                    checked += 1
                    found += (cache / f"{cache_key(LIVE, request, case.source, repeat, 1)}.json").exists()
        self.assertEqual(found, checked)
        self.assertEqual(checked, 84)

    def test_legacy_load_is_unchanged(self):
        cases = benchmark.load_cases(REPO / "corpus", ["all"])
        self.assertEqual(len(cases), 21)
        for case in cases:
            self.assertIsNone(case.dialect)
            self.assertEqual(case.oracle_source, case.source)


class Cli(unittest.TestCase):
    def dry(self, *arguments: str) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(benchmark.main(["--dry-run", *arguments]), 0)
        return out.getvalue()

    def test_dry_run_on_each_set(self):
        for name in SETS:
            text = self.dry("--corpus-dir", str(HARD / name), "--model", "claude-sonnet-5-5:1", "claude-opus-5-5:1")
            with self.subTest(name):
                self.assertIn("TOTAL", text)
                self.assertIn("of which claude-opus-5-5", text)

    def test_form_defaults_to_the_four_programs(self):
        text = self.dry("--form", "ecc_persistent", "--modes", "llm_only")
        for name in benchmark.ECC_PERSISTENT_PROGRAMS:
            self.assertIn(name, text)
        self.assertNotIn("00_latch", text)

    def test_legacy_dry_run_prints_no_new_lines(self):
        self.assertNotIn("of which", self.dry("--programs", "00_latch", "--model", "claude-sonnet-5-5:1", "claude-opus-5-5:1"))

    def test_stress_uses_its_recorded_max_tokens(self):
        case = next(iter(benchmark.load_set(HARD / "stress")))
        self.assertEqual(case.max_tokens, 21333)
        self.assertEqual(benchmark.tokens_for(case, None), 21333)
        self.assertEqual(benchmark.tokens_for(case, 9000), 9000)
        self.assertIn("own recorded max_tokens=21333", self.dry("--corpus-dir", str(HARD / "stress"), "--model", "claude-sonnet-5-5:1"))
        other = next(iter(benchmark.load_set(HARD / "public_st")))
        self.assertEqual(benchmark.tokens_for(other, None), DEFAULT_MAX_TOKENS)

    def test_the_footer_says_what_the_plan_counts(self):
        with_fallback = self.dry("--corpus-dir", str(HARD / "stress"), "--model", "claude-sonnet-5-5:1")
        without = self.dry("--corpus-dir", str(HARD / "stress"), "--model", "claude-sonnet-5-5:1", "--no-fallbacks")
        self.assertIn("also runs a fallback model", with_fallback)
        self.assertNotIn("also runs a fallback model", without)
        self.assertIn("Server-side fallback is off", without)

    def test_the_plan_labels_each_vendor_set(self):
        self.assertIn("TIA-style, never compiled, judged by matiec readings", self.dry("--corpus-dir", str(HARD / "siemens_scl")))
        self.assertIn("Logix-flavoured dialect with invented instructions", self.dry("--corpus-dir", str(HARD / "rockwell_st")))
        self.assertIn("say nothing about model against baseline", self.dry("--corpus-dir", str(HARD / "public_st")))

    def test_unknown_program_in_a_set(self):
        with self.assertRaises(SystemExit):
            self.dry("--corpus-dir", str(HARD / "stress"), "--programs", "nothing")

    def test_form_costs_more_than_the_old_prompt_in_the_plan(self):
        args = argparse.Namespace(effort=DEFAULT_EFFORT, max_tokens=DEFAULT_MAX_TOKENS, no_fallbacks=False)
        cases = benchmark.load_cases(REPO / "corpus", ["00_latch"])
        plain = benchmark.planned_rows(cases, ["llm_only"], [("claude-sonnet-5-5", 1)], args)
        strict = benchmark.planned_rows(cases, ["llm_only"], [("claude-sonnet-5-5", 1)], args, "ecc_persistent")
        self.assertGreater(strict[0]["worst_case_usd"], plain[0]["worst_case_usd"])


class ProtectedResults(unittest.TestCase):
    def test_writing_to_the_published_results_is_refused(self):
        client = FakeClient(lambda request: FakeReply(text=""))
        for directory in (EARLIER, EARLIER / "reports" / "x"):
            with self.assertRaisesRegex(ValueError, "never written"):
                benchmark.run_benchmark([], [], [], client, None, directory)
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(ValueError, "never written"):
                benchmark.run_benchmark([], [], [], client, None, Path(out), store_dir=EARLIER)

    def test_fake_results_cannot_land_in_the_live_hard_store(self):
        client = FakeClient(lambda request: FakeReply(text=""))
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(ValueError, "fake results"):
                benchmark.run_benchmark([], [], [], client, None, Path(out), store_dir=benchmark.HARD_LIVE_DIR)


class Rendering(unittest.TestCase):
    def test_report_compares_a_pass_with_both_deterministic_tiers(self):
        base = {"tuning_equal": None, "heldout_equal": None, "attempts": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "new_spend_usd": 0.0,
                "source_has_case": False, "ecc_states": None, "working_states": None, "algorithms": None, "restructured": None, "ecc_persistent": None, "control_states": None, "repeat": 0}
        rows = [
            {**base, "program": "a", "set": "siemens_scl", "mode": "baseline", "model": "deterministic-translator", "baseline_status": "rejected", "frontend_status": "passed", "passed": False, "failure_category": "baseline_rejected"},
            {**base, "program": "b", "set": "siemens_scl", "mode": "baseline", "model": "deterministic-translator", "baseline_status": "passed", "frontend_status": "passed", "passed": True, "tuning_equal": True, "heldout_equal": True, "failure_category": None},
            {**base, "program": "c", "set": "siemens_scl", "mode": "baseline", "model": "deterministic-translator", "baseline_status": "rejected", "frontend_status": "rejected", "passed": False, "failure_category": "baseline_rejected"},
            {**base, "program": "a", "set": "siemens_scl", "mode": "llm_only", "model": "claude-sonnet-5-5", "passed": True, "tuning_equal": True, "heldout_equal": True, "attempts": 1, "failure_category": None, "ecc_persistent": True, "ecc_verdict": "persistent", "restructured": True},
            {**base, "program": "b", "set": "siemens_scl", "mode": "llm_only", "model": "claude-sonnet-5-5", "passed": True, "tuning_equal": True, "heldout_equal": True, "attempts": 1, "failure_category": None, "ecc_persistent": False, "ecc_verdict": "not_persistent", "restructured": True},
            {**base, "program": "c", "set": "siemens_scl", "mode": "llm_only", "model": "claude-sonnet-5-5", "passed": True, "tuning_equal": True, "heldout_equal": True, "attempts": 1, "failure_category": None, "ecc_persistent": None, "ecc_verdict": "needs_reading", "restructured": True},
        ]
        with tempfile.TemporaryDirectory() as out:
            document = benchmark.write_reports(rows, "fake", Path(out), None, {"sets": ["siemens_scl"], "form": None})
            text = (Path(out) / "benchmark.md").read_text(encoding="utf-8")
        self.assertEqual(document["baseline"], {"rejected": ["a", "c"], "passed": ["b"], "failed": []})
        self.assertEqual(document["baseline_frontend"], {"rejected": ["c"], "passed": ["a", "b"], "failed": []})
        model = next(entry for entry in document["aggregate"] if entry["mode"] == "llm_only")
        self.assertEqual(
            (model["passed_where_translator_rejected"], model["passed_where_frontend_did_not_pass"], model["passed_and_persistent"], model["passed_needs_reading"], model["restructured_and_passed"]),
            (2, 1, 1, 1, 3),
        )
        self.assertIn("| translator | rejected | 2 | a, c |", text)
        self.assertIn("| frontend+translator | rejected | 1 | c |", text)
        self.assertIn("| Translator | Frontend+translator |", text)
        self.assertIn("Passed where translator rejected | Passed where frontend+translator did not pass", text)
        self.assertIn("| Persistent |", text)
        self.assertIn("needs reading", text)
        self.assertIn("never compiled by TIA Portal", text)
        self.assertIn("TIA-style, never compiled, judged by matiec readings", text)
        self.assertIn("1 of 2 of these programs fall to a small syntax front-end", text)
        self.assertIn("This does not show the model can do what deterministic code cannot", text)
        self.assertNotIn("something the baseline could not do", text)


class ReferenceRunner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reference_run.ensure_image()

    def one(self, inputs: str, outputs: str, body: str, values: list[dict]) -> list:
        source = f"FUNCTION_BLOCK F\nVAR_INPUT {inputs} END_VAR\nVAR_OUTPUT {outputs} END_VAR\n{body}\nEND_FUNCTION_BLOCK\n"
        return [scan["Y"] for scan in reference_run.run_reference(source, {"scan_ms": 10, "scans": values})["scans"]]

    def test_real_to_int_links_and_rounds_half_to_even(self):
        values = [{"X": x} for x in (1.5, 2.5, -1.5, -2.5, 0.5, -0.5, 3.0, 0.75)]
        self.assertEqual(self.one("X : REAL;", "Y : INT;", "Y := REAL_TO_INT(X);", values), [2, 2, -2, -2, 0, 0, 3, 1])

    def test_real_to_dint_links_and_rounds_half_to_even(self):
        values = [{"X": x} for x in (1.5, 2.5, 100000.5, -3.5)]
        self.assertEqual(self.one("X : REAL;", "Y : DINT;", "Y := REAL_TO_DINT(X);", values), [2, 2, 100000, -4])

    def test_forte_gives_the_same_on_rounding_and_expt(self):
        """If these differed, no migration of a program that uses them could pass."""
        source = (
            "FUNCTION_BLOCK F\nVAR_INPUT X : REAL; END_VAR\nVAR_OUTPUT A : INT; B : DINT; C : REAL; END_VAR\n"
            "A := REAL_TO_INT(X);\nB := REAL_TO_DINT(X);\nC := ABS(X) ** 0.5;\nEND_FUNCTION_BLOCK\n"
        )
        stimulus = {"scan_ms": 10, "scans": [{"X": x} for x in (1.5, 2.5, -1.5, -2.5, 0.5, -0.5, 3.0, 0.75, 1000.75, 100.25)]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stimulus.json"
            path.write_text(json.dumps(stimulus))
            outcome = forte_eval.evaluate(fbt.write_fbt(translate_source(source)), path, reference_run.run_reference(source, stimulus))
        self.assertEqual(outcome.status, "equal", outcome.report)

    def test_expt_and_math_functions_link(self):
        self.assertEqual(self.one("X : REAL;", "Y : REAL;", "Y := X ** 2.0;", [{"X": 1.5}, {"X": 3.0}]), [2.25, 9.0])
        self.assertEqual(self.one("X : REAL;", "Y : REAL;", "Y := SQRT(X);", [{"X": 4.0}]), [2.0])

    def test_marker_selects_the_block_under_test(self):
        source = (
            "FUNCTION_BLOCK HELPER\nVAR_INPUT A : BOOL; END_VAR\nVAR_OUTPUT B : BOOL; END_VAR\nB := A;\nEND_FUNCTION_BLOCK\n"
            "(* st2fb:dut *)\nFUNCTION_BLOCK OUTER\nVAR_INPUT X : BOOL; END_VAR\nVAR_OUTPUT Y : BOOL; END_VAR\nVAR H : HELPER; END_VAR\n"
            "H(A := X);\nY := NOT H.B;\nEND_FUNCTION_BLOCK\n"
        )
        interface = reference_run.scan_interface(source)
        self.assertEqual((interface.fb_name, [v.name for v in interface.inputs], [v.name for v in interface.outputs]), ("OUTER", ["X"], ["Y"]))
        trace = reference_run.run_reference(source, {"scan_ms": 10, "scans": [{"X": True}, {"X": False}]})
        self.assertEqual([scan["Y"] for scan in trace["scans"]], [False, True])

    def test_helper_function_adds_nothing_to_the_interface(self):
        source = "FUNCTION G : INT\nVAR_INPUT Q : INT; END_VAR\nG := Q + 1;\nEND_FUNCTION\nFUNCTION_BLOCK F\nVAR_INPUT X : INT; END_VAR\nVAR_OUTPUT Y : INT; END_VAR\nY := G(X);\nEND_FUNCTION_BLOCK\n"
        self.assertEqual([v.name for v in reference_run.scan_interface(source).inputs], ["X"])

    def test_two_blocks_without_a_marker_are_still_refused(self):
        with self.assertRaisesRegex(reference_run.BadInput, "exactly one"):
            reference_run.scan_interface("FUNCTION_BLOCK A\nEND_FUNCTION_BLOCK\nFUNCTION_BLOCK B\nEND_FUNCTION_BLOCK\n")

    def test_two_markers_are_refused(self):
        with self.assertRaisesRegex(reference_run.BadInput, "marker"):
            reference_run.scan_interface("(* st2fb:dut *) FUNCTION_BLOCK A\nEND_FUNCTION_BLOCK\n(* st2fb:dut *) FUNCTION_BLOCK B\nEND_FUNCTION_BLOCK\n")


class MutationTool(unittest.TestCase):
    def test_every_corpus_mutant_list_is_unchanged(self):
        recorded = json.loads((REPO / "corpus" / "mutation_after_all.json").read_text(encoding="utf-8"))
        for result in recorded:
            directory = REPO / "corpus" / result["program"]
            stimulus = json.loads((directory / "stimulus.json").read_text(encoding="utf-8"))
            mutants = mutate.st_mutants((directory / "program.st").read_text(encoding="utf-8"), stimulus["scan_ms"])
            selected = mutate.select_mutants(mutants, 100000, f"61499:{result['program']}")
            with self.subTest(result["program"]):
                self.assertEqual([m.description for m in selected], [m["description"] for m in result["mutants"]])

    def test_helper_blocks_are_mutated_too(self):
        source = (
            "FUNCTION_BLOCK H\nVAR_INPUT A : INT; END_VAR\nVAR_OUTPUT B : INT; END_VAR\nB := A + 1;\nEND_FUNCTION_BLOCK\n"
            "(* st2fb:dut *)\nFUNCTION_BLOCK F\nVAR_INPUT X : INT; END_VAR\nVAR_OUTPUT Y : INT; END_VAR\nVAR U : H; END_VAR\nU(A := X);\nY := U.B * 2;\nEND_FUNCTION_BLOCK\n"
        )
        descriptions = [m.description for m in mutate.st_mutants(source)]
        self.assertTrue(any("'+' -> '-'" in d for d in descriptions))
        self.assertTrue(any("'*' -> '/'" in d for d in descriptions))
        # Each mutant stays a whole file, so the helper is still there.
        for mutant in mutate.st_mutants(source):
            self.assertIn("FUNCTION_BLOCK H", mutant.text)
            self.assertIn("FUNCTION_BLOCK F", mutant.text)

    def test_new_constructs(self):
        source = "FUNCTION_BLOCK F\nVAR_INPUT X : REAL; END_VAR\nVAR_OUTPUT Y : REAL; END_VAR\nVAR A : ARRAY[0..2] OF REAL; I : INT; W : WORD; END_VAR\n" \
                 "W := 16#00FF;\nREPEAT\n  I := I + 1;\n  IF I > 2 THEN\n    EXIT;\n  END_IF;\nUNTIL A[I] > X\nEND_REPEAT;\nY := X ** 2.0;\nEND_FUNCTION_BLOCK\n"
        descriptions = [m.description for m in mutate.st_mutants(source)]
        self.assertTrue(any("UNTIL condition" in d for d in descriptions))
        self.assertTrue(any("removed 'EXIT;'" in d for d in descriptions))
        self.assertTrue(any("'**' -> '*'" in d for d in descriptions))
        self.assertFalse(any("removed 'REPEAT" in d for d in descriptions))

    def test_every_survivor_has_been_analysed(self):
        results = json.loads((HARD / "mutation_results.json").read_text(encoding="utf-8"))
        notes = json.loads((HARD / "mutation_survivor_notes.json").read_text(encoding="utf-8"))["survivors"]
        survivors = [f"{r['program']}|{m['description']}" for r in results for m in r["mutants"] if m["outcome"] == "survived"]
        self.assertEqual([survivor for survivor in survivors if survivor not in notes], [])
        self.assertEqual([note for note in survivors if notes[note]["verdict"] not in ("equivalent", "equivalent on any realistic stimulus", "meaningless", "gap, listed")], [])
        self.assertTrue(all(r["control_equal"] for r in results))

    def test_the_results_on_disk_are_uncapped_and_on_every_scored_stimulus(self):
        results = {r["program"]: r for r in json.loads((HARD / "mutation_results.json").read_text(encoding="utf-8"))}
        self.assertEqual(len(results), 23)
        for program_dir in mutate.program_dirs(HARD):
            result = results[program_dir.name]
            source = mutate.oracle_file(program_dir).read_text(encoding="utf-8")
            stimulus = json.loads((program_dir / "stimulus.json").read_text(encoding="utf-8"))
            with self.subTest(program_dir.name):
                self.assertEqual([m["description"] for m in result["mutants"]], [m.description for m in mutate.st_mutants(source, stimulus["scan_ms"])])
                for mutant in result["mutants"]:
                    self.assertEqual(set(mutant["by_stimulus"]), {"stimulus", "heldout_stimulus", "heldout_stimulus_2"})

    def test_oracle_of_a_paired_program_is_the_reference(self):
        self.assertEqual(mutate.oracle_file(HARD / "siemens_scl/s01_conveyor_starter").name, "reference.st")
        self.assertEqual(mutate.oracle_file(HARD / "unsupported_st/u03_tank_strapping").name, "program.st")
        self.assertEqual(mutate.oracle_file(REPO / "corpus/00_latch").name, "program.st")

    def test_program_dirs_descend_one_level_only_if_needed(self):
        self.assertEqual(len(mutate.program_dirs(REPO / "corpus")), 21)
        self.assertEqual(len(mutate.program_dirs(HARD)), 23)


class OracleAndControls(unittest.TestCase):
    """Real matiec and FORTE on every program. The same work as `python3 -m st2fb.llm.hard_check`, both deterministic tiers included."""

    def test_all(self):
        jobs = [(case, HARD / case.set_name / case.name) for case in all_cases()]
        reference_run.ensure_image()
        with reference_run.Container() as container, ThreadPoolExecutor(max_workers=hard_check.JOBS) as pool:
            results = list(pool.map(lambda job: hard_check.check_case(job[0], job[1], container), jobs))
        for result in results:
            with self.subTest(result["program"]):
                self.assertEqual(result["control"], {"tuning": "equal", "heldout_stimulus": "equal", "heldout_stimulus_2": "equal"})
                self.assertEqual(result["unexplained_static"], [])
                self.assertFalse(result["same_stimulus"])
                self.assertEqual(result["identical_prefix_scans"], 0)
                self.assertEqual(result["frontend"]["frontend_status"], "passed" if result["program"] in PASS_FRONTEND else "rejected", result["frontend"])
                self.assertFalse(hard_check.case_failed(result))
                if result["program"] in ACCEPTED_BY_BASELINE:
                    self.assertEqual(result["baseline"], {"status": "accepted", "result": "passed"})
                else:
                    self.assertEqual(result["baseline"]["status"], "rejected")


class Pairing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("check_pairing", REPO / "scripts/check_pairing.py")
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        spec.loader.exec_module(cls.module)
        reference_run.ensure_image()

    def compare_with(self, key: str, reference: str, container) -> dict:
        directory = HARD / key
        stimulus = json.loads((directory / "pairing_stimulus.json").read_text(encoding="utf-8"))
        trace = reference_run.run_reference(reference, stimulus, container)
        rows = [{"t_ms": i * stimulus["scan_ms"], **row} for i, row in enumerate(self.module.MODELS[key](stimulus["scans"], stimulus["scan_ms"]))]
        return compare.compare_traces(trace, {"source": "forte", "scan_ms": stimulus["scan_ms"], "outputs": trace["outputs"], "scans": rows})

    def test_models_read_from_the_vendor_file_agree_with_each_reference(self):
        with reference_run.Container() as container:
            for key in self.module.MODELS:
                with self.subTest(key):
                    report = self.compare_with(key, (HARD / key / "reference.st").read_text(encoding="utf-8"), container)
                    self.assertTrue(report["equal"], report["first_divergence"])

    def test_the_front_end_agrees_with_all_twelve_references_on_every_stimulus(self):
        self.assertEqual(len(self.module.PAIRED), 12)
        with reference_run.Container() as container:
            for key in self.module.PAIRED:
                for name, report in self.module.frontend_against_reference(key, container).items():
                    with self.subTest(key, stimulus=name):
                        self.assertTrue(report["equal"], report["first_divergence"])

    def test_the_check_would_notice_a_wrong_translation(self):
        """Negative control: a single edit to a reference must make it disagree with the model."""
        with reference_run.Container() as container:
            for key in self.module.MODELS:
                reference = (HARD / key / "reference.st").read_text(encoding="utf-8")
                wrong = re.sub(r"\bAND NOT\b", "OR NOT", reference, count=1)
                self.assertNotEqual(wrong, reference)
                with self.subTest(key):
                    self.assertFalse(self.compare_with(key, wrong, container)["equal"])


class EndToEnd(unittest.TestCase):
    """Scripted replies through real FORTE and matiec. No model and no network."""

    @classmethod
    def setUpClass(cls):
        reference_run.ensure_image()

    def run_set(self, cases, reply, out: Path, form=None, modes=("llm_repair",)):
        requests = []

        def recording(request: LlmRequest) -> FakeReply:
            requests.append(request)
            return reply(request, len(requests))

        document, code = benchmark.run_benchmark(
            cases, list(modes), [("claude-sonnet-5-5", 1)], FakeClient(recording), None, out,
            hard={"sets": sorted({case.set_name for case in cases if case.set_name}), "form": form},
        )
        self.assertEqual(code, 0)
        return document, requests

    def test_scl_program_end_to_end(self):
        case = next(c for c in benchmark.load_set(HARD / "siemens_scl") if c.name == "s01_conveyor_starter")
        good = fbt.write_fbt(translate_source(case.oracle))
        # First a wrong one, so that the repair prompt is seen as well.
        wrong = good.replace("o_horn := statRunRequest AND NOT statHornTimer_Q;", "o_horn := statRunRequest;")
        self.assertNotEqual(wrong, good)
        with tempfile.TemporaryDirectory() as directory:
            document, requests = self.run_set([case], lambda r, n: FakeReply(text=wrong if n == 1 else good), Path(directory))
            text = (Path(directory) / "benchmark.md").read_text(encoding="utf-8")
        rows = {row["mode"]: row for row in document["results"]}
        self.assertEqual(rows["baseline"]["baseline_status"], "rejected")
        self.assertIs(rows["baseline"]["passed"], False)
        self.assertTrue(rows["llm_repair"]["passed"])
        self.assertEqual(rows["llm_repair"]["attempts"], 2)
        self.assertEqual(rows["llm_repair"]["dialect"], "siemens_scl")
        self.assertIn("| rejected | 1 | s01_conveyor_starter |", text)

        self.assertEqual(len(requests), 2)
        for request in requests:
            self.assertIn("#statHornTimer", request.user)  # The model sees the SCL.
            for forbidden in ("Hand-written reference", "statHornTimer(IN := statRunRequest, PT := i_hornTime, ET => o_hornElapsed)"):
                self.assertNotIn(forbidden, request.user)
                self.assertNotIn(forbidden, request.system)
            self.assertNotIn("heldout", (request.user + request.system).lower())
        self.assertIn("Siemens SCL", requests[0].system)

    def test_a_run_must_pass_every_held_out_file(self):
        """A frozen scan period passes tuning and the first held-out file, so only the second can fail it. It is scored as overfit, and gets no repair."""
        case = next(c for c in benchmark.load_set(HARD / "siemens_scl") if c.name == "s01_conveyor_starter")
        good = fbt.write_fbt(translate_source(case.oracle))
        frozen = good.replace("ST2FB_NOW := ST2FB_NOW + SCAN_DT;", "ST2FB_NOW := ST2FB_NOW + T#10ms;")
        frozen = re.sub(r'<With Var="SCAN_DT"\s*/>', "", frozen)
        frozen = re.sub(r'<VarDeclaration Name="SCAN_DT"[^>]*/>', "", frozen)
        with tempfile.TemporaryDirectory() as directory:
            document, requests = self.run_set([case], lambda r, n: FakeReply(text=frozen), Path(directory))
        row = next(r for r in document["results"] if r["mode"] == "llm_repair")
        self.assertTrue(row["tuning_equal"])
        self.assertIs(row["heldout_equal"], False)
        self.assertIs(row["passed"], False)
        self.assertEqual(row["failure_category"], "heldout_different")
        self.assertEqual(row["heldout_files"], {"heldout_stimulus.json": "equal", "heldout_stimulus_2.json": "different"})
        self.assertEqual(len(requests), 1)

    def test_stress_requests_use_the_recorded_max_tokens(self):
        case = next(iter(benchmark.load_set(HARD / "stress")))
        with tempfile.TemporaryDirectory() as directory:
            document, requests = self.run_set([case], lambda r, n: FakeReply(text="not an fbt"), Path(directory), modes=("llm_only",))
        self.assertEqual(requests[0].config.max_tokens, 21333)
        self.assertEqual(next(r for r in document["results"] if r["mode"] == "llm_only")["max_tokens"], 21333)

    def test_rejected_baseline_and_a_model_failure_are_both_reported(self):
        case = next(c for c in benchmark.load_set(HARD / "unsupported_st") if c.name == "u03_tank_strapping")
        with tempfile.TemporaryDirectory() as directory:
            document, _ = self.run_set([case], lambda r, n: FakeReply(text="not an fbt"), Path(directory), modes=("llm_only",))
        rows = {row["mode"]: row for row in document["results"]}
        self.assertEqual(rows["baseline"]["failure_category"], "baseline_rejected")
        self.assertEqual(rows["llm_only"]["failure_category"], "xml_error")
        self.assertFalse(rows["llm_only"]["passed"])

    def test_default_fake_client_survives_a_rejected_source(self):
        client = benchmark.echo_translator_client()
        case = benchmark.load_set(HARD / "siemens_scl")[0]
        request = LlmRequest(system="", user=prompts.generate_prompt(case.source, prompts.PromptProfile("siemens_scl")), config=LlmConfig("claude-sonnet-5-5"), tag="")
        self.assertIn("cannot translate", client.complete(request).text)

    def test_form_is_reported_and_never_decides_the_pass(self):
        cases = benchmark.load_cases(REPO / "corpus", ["06_star_delta"])
        control = (HARD / "ecc_persistent/06_star_delta/control.fbt").read_text(encoding="utf-8")
        wrapper = fbt.write_fbt(translate_source(cases[0].source))
        for reply, persistent in ((control, True), (wrapper, False)):
            with tempfile.TemporaryDirectory() as directory:
                document, requests = self.run_set(cases, lambda r, n, text=reply: FakeReply(text=text), Path(directory), form="ecc_persistent", modes=("llm_only",))
            row = next(r for r in document["results"] if r["mode"] == "llm_only")
            with self.subTest(persistent=persistent):
                self.assertTrue(row["passed"])
                self.assertIs(row["ecc_persistent"], persistent)
                self.assertIn("Required form", requests[0].system)


if __name__ == "__main__":
    unittest.main()
