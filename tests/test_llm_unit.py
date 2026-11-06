"""LLM layer without Docker, without a network and without the SDK. Everything here is a fake."""
import ast
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from st2fb import fbt, forte_eval
from st2fb.llm import benchmark, config, engine, keys, prompts
from st2fb.llm.budget import BudgetExceeded, Ledger
from st2fb.llm.cache import ResponseCache, cache_key
from st2fb.llm.client import FAKE, LIVE, FakeClient, FakeReply, FatalApiError, LlmRequest, LlmResponse, TransientApiError
from st2fb.llm.config import LlmConfig, UsageEntry, cost_usd, input_token_bound, worst_case_usd
from st2fb.llm.gateway import Gateway
from st2fb.translate import STD_FBS, translate_source

REPO = Path(__file__).resolve().parent.parent
FAKE_KEY = "sk-ant-FAKE-KEY-FOR-TESTS-0123456789"
CONFIG = LlmConfig()


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st2fb-llm-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)


class KeyHandling(TempDirCase):
    def write_env(self, text):
        path = self.tmp / "test.env"
        path.write_text(text)
        return path

    def test_reads_only_the_project_variable(self):
        path = self.write_env(f"# comment\nANTHROPIC_API_KEY=wrong\nOTHER=x\nST2FB_ANTHROPIC_API_KEY={FAKE_KEY}\n")
        self.assertEqual(keys.load_api_key(path), FAKE_KEY)

    def test_never_falls_back_to_the_generic_variable(self):
        path = self.write_env("ANTHROPIC_API_KEY=wrong\n")
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "from-env", keys.ENV_NAME: "from-env-too"}):
            with self.assertRaises(keys.ApiKeyError):
                keys.load_api_key(path)

    def test_does_not_change_the_environment(self):
        path = self.write_env(f"ST2FB_ANTHROPIC_API_KEY={FAKE_KEY}\n")
        before = dict(os.environ)
        keys.load_api_key(path)
        self.assertEqual(dict(os.environ), before)

    def test_quotes_and_export(self):
        self.assertEqual(keys.load_api_key(self.write_env(f'export ST2FB_ANTHROPIC_API_KEY="{FAKE_KEY}"\n')), FAKE_KEY)
        self.assertEqual(keys.load_api_key(self.write_env(f"ST2FB_ANTHROPIC_API_KEY='{FAKE_KEY}'\n")), FAKE_KEY)

    def test_errors_do_not_quote_the_file(self):
        secret_line = f"ST2FB_ANTHROPIC_API_KEYX={FAKE_KEY}\n"
        with self.assertRaises(keys.ApiKeyError) as caught:
            keys.load_api_key(self.write_env(secret_line))
        self.assertNotIn(FAKE_KEY, str(caught.exception))
        with self.assertRaises(keys.ApiKeyError):
            keys.load_api_key(self.write_env("ST2FB_ANTHROPIC_API_KEY=\n"))
        with self.assertRaises(keys.ApiKeyError):
            keys.load_api_key(self.tmp / "missing.env")

    def test_redact(self):
        self.assertEqual(keys.redact(f"bad key {FAKE_KEY} here", FAKE_KEY), "bad key [REDACTED] here")


class Prices(unittest.TestCase):
    def test_default_and_allowed_models(self):
        self.assertEqual(LlmConfig().model, "claude-sonnet-5-5")
        LlmConfig("claude-opus-5-5")
        with self.assertRaises(ValueError):
            LlmConfig("gpt-4")

    def test_prices_as_given(self):
        self.assertEqual(config.PRICES_AS_OF, "2026-10-06")
        self.assertEqual((config.PRICES["claude-sonnet-5-5"].input, config.PRICES["claude-sonnet-5-5"].output), (2.0, 10.0))
        self.assertEqual((config.PRICES["claude-opus-5-5"].input, config.PRICES["claude-opus-5-5"].output), (4.0, 20.0))

    def test_cost_from_usage(self):
        entry = UsageEntry("claude-sonnet-5-5", 1_000_000, 1_000_000)
        self.assertAlmostEqual(cost_usd([entry]), 12.0)
        cached = UsageEntry("claude-opus-5-5", 0, 0, 1_000_000, 1_000_000)
        self.assertAlmostEqual(cost_usd([cached]), 5.0 + 0.2)

    def test_each_fallback_hop_is_billed_at_its_own_rate(self):
        hops = [UsageEntry("claude-opus-5-5", 100, 0), UsageEntry("claude-opus-4-8", 100, 100)]
        self.assertAlmostEqual(cost_usd(hops), (100 * 4 + 100 * 5 + 100 * 25) / 1e6)

    def test_unknown_model_is_priced_at_the_dearest(self):
        self.assertAlmostEqual(cost_usd([UsageEntry("claude-future", 0, 1_000_000)]), 25.0)

    def test_worst_case_is_an_upper_bound_with_room_for_a_fallback(self):
        no_fallback = LlmConfig(fallbacks=False)
        self.assertAlmostEqual(worst_case_usd(no_fallback, 1000), (1000 * 2.5 + 16000 * 10) / 1e6)
        self.assertAlmostEqual(worst_case_usd(LlmConfig(), 1000), 2 * (1000 * 2.5 + 16000 * 10) / 1e6)
        opus = LlmConfig("claude-opus-5-5")
        self.assertAlmostEqual(worst_case_usd(opus, 0), (16000 * 20 + 16000 * 25) / 1e6)

    def test_max_tokens_stays_under_the_sdk_limit(self):
        with self.assertRaises(ValueError):
            LlmConfig(max_tokens=30000)


class Budget(TempDirCase):
    def ledger(self, kind=FAKE):
        return Ledger(self.tmp / "ledger.jsonl", kind)

    def test_open_reservation_counts_as_its_worst_case(self):
        ledger = self.ledger()
        ledger.reserve(0.5, 1.0, "a")
        self.assertAlmostEqual(ledger.spent_usd(), 0.5)

    def test_settling_replaces_the_reservation_with_the_real_cost(self):
        ledger = self.ledger()
        reservation = ledger.reserve(0.5, 1.0, "a")
        ledger.settle(reservation, 0.01, [], "req")
        self.assertAlmostEqual(ledger.spent_usd(), 0.01)

    def test_release(self):
        ledger = self.ledger()
        ledger.release(ledger.reserve(0.5, 1.0, "a"), "400")
        self.assertEqual(ledger.spent_usd(), 0.0)

    def test_refuses_what_might_not_fit(self):
        ledger = self.ledger()
        with self.assertRaises(BudgetExceeded):
            ledger.reserve(1.5, 1.0, "a")
        self.assertEqual(ledger.spent_usd(), 0.0)

    def test_refuses_once_the_cap_is_reached_even_for_a_free_request(self):
        ledger = self.ledger()
        ledger.settle(ledger.reserve(1.0, 1.0, "a"), 1.0, [], None)
        with self.assertRaises(BudgetExceeded):
            ledger.reserve(0.0, 1.0, "b")

    def test_survives_a_restart(self):
        self.ledger().settle(self.ledger().reserve(0.4, 1.0, "a"), 0.4, [], None)
        self.assertAlmostEqual(self.ledger().spent_usd(), 0.4)

    def test_fake_spend_does_not_count_against_live(self):
        fake = self.ledger(FAKE)
        fake.settle(fake.reserve(0.4, 1.0, "a"), 0.4, [], None)
        self.assertEqual(self.ledger(LIVE).spent_usd(), 0.0)


def request(user="u", system="s", cfg=CONFIG):
    return LlmRequest(system=system, user=user, config=cfg, tag="t")


class Cache(TempDirCase):
    def test_every_part_of_the_key_matters(self):
        base = cache_key(FAKE, request(), "src", 0, 1)
        self.assertEqual(base, cache_key(FAKE, request(), "src", 0, 1))
        others = [
            cache_key(LIVE, request(), "src", 0, 1),
            cache_key(FAKE, request(user="v"), "src", 0, 1),
            cache_key(FAKE, request(system="z"), "src", 0, 1),
            cache_key(FAKE, request(cfg=LlmConfig("claude-opus-5-5")), "src", 0, 1),
            cache_key(FAKE, request(cfg=LlmConfig(effort="high")), "src", 0, 1),
            cache_key(FAKE, request(cfg=LlmConfig(max_tokens=100)), "src", 0, 1),
            cache_key(FAKE, request(), "other", 0, 1),
            cache_key(FAKE, request(), "src", 1, 1),
            cache_key(FAKE, request(), "src", 0, 2),
        ]
        self.assertEqual(len(set(others + [base])), len(others) + 1)

    def test_round_trip_holds_no_credentials(self):
        cache = ResponseCache(self.tmp / "c", FAKE)
        response = LlmResponse("text", "end_turn", (UsageEntry("m", 1, 2),), "m", request_id="r")
        cache.put("k", "tag", response)
        self.assertEqual(cache.get("k"), response)
        self.assertEqual(json.loads((self.tmp / "c" / "k.json").read_text())["client"], "fake")
        self.assertIsNone(cache.get("missing"))

    def test_fake_entry_cannot_be_read_as_live(self):
        ResponseCache(self.tmp / "c", FAKE).put("k", "t", LlmResponse("x", "end_turn", (), "m"))
        self.assertIsNone(ResponseCache(self.tmp / "c", LIVE).get("k"))


class GatewayTests(TempDirCase):
    def gateway(self, client, budget=None):
        ledger = Ledger(self.tmp / "l.jsonl", client.kind)
        cache = ResponseCache(self.tmp / "c", client.kind)
        return Gateway(client, ledger, cache, budget, sleep=lambda s: None), ledger

    def test_live_client_must_have_a_budget(self):
        client = FakeClient([])
        client.kind = LIVE
        with self.assertRaises(ValueError):
            self.gateway(client)

    def test_cache_hit_spends_nothing_and_calls_nothing(self):
        client = FakeClient([FakeReply("a")])
        gateway, ledger = self.gateway(client, 5.0)
        first = gateway.call(request(), "src", 0, 1)
        spent = ledger.spent_usd()
        second = gateway.call(request(), "src", 0, 1)
        self.assertEqual(len(client.requests), 1)
        self.assertTrue(second.cached)
        self.assertEqual(second.new_spend_usd, 0.0)
        self.assertEqual(second.cost_usd, first.cost_usd)
        self.assertEqual(ledger.spent_usd(), spent)

    def test_repeats_are_independent_samples(self):
        client = FakeClient([FakeReply("a"), FakeReply("b")])
        gateway, _ = self.gateway(client, 5.0)
        self.assertEqual(gateway.call(request(), "src", 0, 1).response.text, "a")
        self.assertEqual(gateway.call(request(), "src", 1, 1).response.text, "b")

    def test_budget_is_checked_before_the_request(self):
        client = FakeClient([FakeReply("a")])
        gateway, _ = self.gateway(client, 0.0001)
        with self.assertRaises(BudgetExceeded):
            gateway.call(request(), "src", 0, 1)
        self.assertEqual(client.requests, [])

    def test_transient_error_retries_then_succeeds(self):
        client = FakeClient([FakeReply(raises=TransientApiError("429")), FakeReply("ok")])
        gateway, ledger = self.gateway(client, 5.0)
        self.assertEqual(gateway.call(request(), "src", 0, 1).response.text, "ok")
        self.assertEqual(len(client.requests), 2)
        self.assertAlmostEqual(ledger.spent_usd(), cost_usd([UsageEntry(CONFIG.model, 1000, 1000)]))

    def test_transient_error_gives_up_after_three_sends(self):
        client = FakeClient([FakeReply(raises=TransientApiError("500"))] * 3)
        gateway, ledger = self.gateway(client, 5.0)
        with self.assertRaises(TransientApiError):
            gateway.call(request(), "src", 0, 1)
        self.assertEqual(len(client.requests), 3)
        self.assertEqual(ledger.spent_usd(), 0.0)

    def test_lost_connection_keeps_the_worst_case_on_the_ledger(self):
        client = FakeClient([FakeReply(raises=TransientApiError("lost", billed_unknown=True)), FakeReply("ok")])
        gateway, ledger = self.gateway(client, 5.0)
        gateway.call(request(), "src", 0, 1)
        worst = worst_case_usd(CONFIG, input_token_bound("s", "u"))
        self.assertGreaterEqual(ledger.spent_usd(), worst)

    def test_fatal_error_releases_and_does_not_retry(self):
        client = FakeClient([FakeReply(raises=FatalApiError("400"))])
        gateway, ledger = self.gateway(client, 5.0)
        with self.assertRaises(FatalApiError):
            gateway.call(request(), "src", 0, 1)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(ledger.spent_usd(), 0.0)

    def test_failed_replies_are_not_cached(self):
        client = FakeClient([FakeReply(raises=FatalApiError("400")), FakeReply("ok")])
        gateway, _ = self.gateway(client, 5.0)
        with self.assertRaises(FatalApiError):
            gateway.call(request(), "src", 0, 1)
        self.assertEqual(gateway.call(request(), "src", 0, 1).response.text, "ok")


class Prompts(unittest.TestCase):
    def test_no_placeholder_survives(self):
        for text in (prompts.system_prompt(), prompts.generate_prompt("S"), prompts.repair_prompt("S", "P", "F")):
            self.assertNotIn("{{", text)

    def test_system_prompt_does_not_depend_on_the_program(self):
        self.assertEqual(prompts.system_prompt(), prompts.system_prompt())
        self.assertNotIn("{{SOURCE}}", (prompts.PROMPT_DIR / "system.md").read_text())

    def test_asks_for_the_contract_and_for_idiomatic_structure(self):
        system = prompts.system_prompt()
        for needle in ("`REQ`", "`CNF`", "SCAN_DT", "EC states", "ST2FB_NOW", "one working state"):
            self.assertIn(needle, system)

    def test_semantics_file_matches_the_translator(self):
        text = (prompts.PROMPT_DIR / "std_fb_semantics.md").read_text()
        for name, std in STD_FBS.items():
            self.assertIn(f"### {name}", text)
            self.assertIn(textwrap.dedent(std.body).strip("\n").rstrip(), text)

    def test_example_parses_and_is_restructured(self):
        example = (prompts.PROMPT_DIR / "example.fbt").read_text()
        fbt.parse_fbt(example)
        self.assertTrue(engine.ecc_structure(example)["restructured"])

    def test_no_prompt_or_engine_source_mentions_held_out(self):
        for path in list(prompts.PROMPT_DIR.iterdir()):
            self.assertNotIn("heldout", path.read_text().lower().replace("-", "").replace(" ", ""), path.name)
        tree = ast.parse((REPO / "st2fb/llm/engine.py").read_text())
        names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertFalse({name for name in names if "heldout" in name.lower()})
        self.assertNotIn("heldout", (REPO / "st2fb/llm/engine.py").read_text().lower())


class Extraction(unittest.TestCase):
    FB = '<?xml version="1.0"?>\n<FBType Name="X"></FBType>'

    def test_plain_fenced_and_with_prose(self):
        self.assertEqual(engine.extract_fbt(self.FB), self.FB)
        self.assertEqual(engine.extract_fbt(f"```xml\n{self.FB}\n```"), self.FB)
        self.assertEqual(engine.extract_fbt(f"Here it is:\n{self.FB}\nDone."), self.FB)

    def test_nothing_to_extract(self):
        self.assertEqual(engine.extract_fbt(" no xml here "), "no xml here")


class Structure(unittest.TestCase):
    def test_one_state_wrapper_is_not_restructured(self):
        latch = fbt.write_fbt(translate_source((REPO / "corpus/00_latch/program.st").read_text()))
        result = engine.ecc_structure(latch)
        self.assertEqual((result["ecc_states"], result["working_states"]), (2, 1))
        self.assertFalse(result["restructured"])

    def test_unparsable(self):
        self.assertIsNone(engine.ecc_structure("<nope")["ecc_states"])


class FailureDescriptions(unittest.TestCase):
    STIMULUS = {"scan_ms": 10, "scans": [{"A": False}, {"A": True}, {"A": False}, {"A": True}, {"A": True}]}

    def test_each_kind_carries_its_detail(self):
        for status, detail in (
            ("parse_failed", "not well-formed XML"),
            ("plan_failed", "missing With"),
            ("compile_failed", "cannot assign"),
            ("timed_out", "no CNF within"),
            ("crashed", "exited"),
        ):
            self.assertIn(detail, engine.describe_failure(forte_eval.Outcome(status, detail), self.STIMULUS))

    def test_divergence_gives_the_scan_the_values_and_the_inputs(self):
        report = {
            "first_divergence": {"scan": 4, "t_ms": 40, "output": "Q", "expected": True, "actual": False},
            "divergences": 3,
            "scans_compared": 5,
            "shape_errors": [],
        }
        text = engine.describe_failure(forte_eval.Outcome("different", report=report), self.STIMULUS)
        for needle in ("scan 4", "t = 40 ms", "output Q", "expected true", "got false", 'scan 3: {"A": true}'):
            self.assertIn(needle, text)


class CachePruning(TempDirCase):
    def test_removes_the_oldest_until_it_fits(self):
        for index, name in enumerate(("old", "mid", "new")):
            entry = self.tmp / name
            entry.mkdir()
            (entry / "forte").write_bytes(b"x" * 100)
            os.utime(entry, (index, index))
        self.assertEqual(forte_eval.prune_cache(150, self.tmp), 2)
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["new"])


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = benchmark.main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class Cli(TempDirCase):
    def test_live_without_a_budget_is_refused_before_any_client_exists(self):
        with mock.patch.object(benchmark, "make_live_client", side_effect=AssertionError("must not be reached")):
            code, _, err = run_cli("--live", "--programs", "00_latch")
        self.assertEqual(code, 2)
        self.assertIn("--budget-usd", err)

    def test_live_with_a_zero_budget_is_refused(self):
        with mock.patch.object(benchmark, "make_live_client", side_effect=AssertionError("must not be reached")):
            code, _, _ = run_cli("--live", "--budget-usd", "0", "--programs", "00_latch")
        self.assertEqual(code, 2)

    def test_dry_run_reads_no_key_and_calls_nothing(self):
        path = self.tmp / "absent.env"
        with mock.patch.object(benchmark, "make_live_client", side_effect=AssertionError("must not be reached")), \
                mock.patch.object(benchmark, "load_api_key", side_effect=AssertionError("must not be read")), \
                mock.patch.object(benchmark, "run_benchmark", side_effect=AssertionError("must not run")):
            code, out, _ = run_cli(
                "--dry-run", "--live", "--budget-usd", "1", "--env-file", str(path),
                "--programs", "00_latch", "--modes", "llm_only",
            )  # fmt: skip
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", out)
        self.assertIn("00_latch", out)
        self.assertIn("at most 1 requests", out)

    def test_dry_run_counts_the_full_plan(self):
        code, out, _ = run_cli("--dry-run", "--model", "claude-sonnet-5-5:3", "claude-opus-5-5:1")
        self.assertEqual(code, 0)
        # Each repair loop's first attempt is llm_only's request, which the cache serves.
        self.assertIn(f"at most {21 * 3 * 3 + 21 * 3} requests", out)

    def test_dry_run_covers_the_worst_case_of_a_real_first_request(self):
        rows = benchmark.planned_rows(
            benchmark.load_cases(REPO / "corpus", ["00_latch"]), ["llm_only"], [("claude-sonnet-5-5", 1)],
            mock.Mock(effort="medium", max_tokens=16000, no_fallbacks=False),
        )  # fmt: skip
        system, user = prompts.system_prompt(), prompts.generate_prompt((REPO / "corpus/00_latch/program.st").read_text())
        expected = worst_case_usd(CONFIG, input_token_bound(system, user))
        self.assertAlmostEqual(rows[0]["worst_case_usd"], expected)

    def test_without_live_only_the_fake_client_is_constructed(self):
        captured = {}

        def stop(cases, modes, models, client, *rest, **kw):
            captured["client"] = client
            return {"client": client.kind}, 0

        with mock.patch.object(benchmark, "make_live_client", side_effect=AssertionError("must not be reached")), \
                mock.patch.object(benchmark, "load_api_key", side_effect=AssertionError("must not be read")), \
                mock.patch.object(benchmark, "run_benchmark", stop):
            code, _, err = run_cli("--budget-usd", "1", "--programs", "00_latch", "--out-dir", str(self.tmp))
        self.assertEqual(code, 0)
        self.assertEqual(captured["client"].kind, FAKE)
        self.assertIn("FAKE CLIENT", err)

    def test_missing_key_is_reported_without_a_traceback(self):
        path = self.tmp / "empty.env"
        path.write_text("OTHER=1\n")
        with mock.patch.dict(sys.modules, {"st2fb.llm.live_client": mock.Mock(AnthropicClient=mock.Mock())}):
            code, _, err = run_cli("--live", "--budget-usd", "1", "--programs", "00_latch", "--env-file", str(path))
        self.assertEqual(code, 2)
        self.assertIn(keys.ENV_NAME, err)

    def test_fake_results_cannot_be_written_to_the_live_directory(self):
        with self.assertRaises(ValueError):
            benchmark.run_benchmark([], [], [], FakeClient([]), None, benchmark.LIVE_DIR)

    def test_unknown_program_and_model(self):
        self.assertNotEqual(run_cli("--dry-run", "--programs", "nope")[0], 0)
        self.assertNotEqual(run_cli("--dry-run", "--model", "gpt-4")[0], 0)


class StandardLibraryOnly(unittest.TestCase):
    def test_only_the_live_client_imports_the_sdk(self):
        for path in REPO.glob("st2fb/**/*.py"):
            tree = ast.parse(path.read_text())
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports |= {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imports.add(node.module.split(".")[0])
            if path.name != "live_client.py":
                self.assertNotIn("anthropic", imports, path)

    def test_nothing_imports_the_live_client_at_module_level(self):
        for path in REPO.glob("st2fb/**/*.py"):
            for node in ast.parse(path.read_text()).body:
                if isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(node.module, "live_client", path)
                    self.assertNotIn("live_client", [alias.name for alias in node.names], path)

    def test_core_and_benchmark_import_without_site_packages(self):
        code = (
            "import sys; import st2fb.translate, st2fb.forte_run, st2fb.compare, st2fb.mutate, st2fb.llm.benchmark; "
            "assert 'anthropic' not in sys.modules; assert 'st2fb.llm.live_client' not in sys.modules"
        )
        result = subprocess.run([sys.executable, "-S", "-c", code], cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class HeldoutStimuli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(REPO / "corpus"))
        cls.addClassCleanup(sys.path.remove, str(REPO / "corpus"))
        spec = importlib.util.spec_from_file_location("generate_heldout", REPO / "corpus/generate_heldout.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)
        cls.programs = sorted(path.parent for path in (REPO / "corpus").glob("*/program.st"))

    def test_every_program_has_one_and_it_regenerates_identically(self):
        self.assertEqual(len(self.programs), 21)
        for directory in self.programs:
            on_disk = (directory / "heldout_stimulus.json").read_text()
            self.assertEqual(self.module.render(self.module.build(directory.name)), on_disk, directory.name)

    def test_generator_uses_a_separate_seed_and_writes_only_its_own_files(self):
        import generate_stimuli

        self.assertNotEqual(self.module.HELDOUT_SEED, generate_stimuli.SEED)
        self.assertEqual(self.module.FILE_NAME, "heldout_stimulus.json")

    def test_tuning_files_still_come_from_the_tuning_generator(self):
        import generate_stimuli

        for name, (scenario, scan_ms, defaults) in generate_stimuli.SCENARIOS.items():
            stimulus = generate_stimuli.Stimulus(name, scan_ms, **defaults)
            scenario(stimulus)
            rows = ",\n".join("  " + json.dumps(scan) for scan in stimulus.scans)
            expected = f'{{"scan_ms": {stimulus.scan_ms}, "scans": [\n{rows}\n]}}\n'
            self.assertEqual((REPO / "corpus" / name / "stimulus.json").read_text(), expected, name)

    def test_held_out_differs_from_tuning_and_lists_the_same_inputs(self):
        for directory in self.programs:
            tuning = json.loads((directory / "stimulus.json").read_text())
            heldout = json.loads((directory / "heldout_stimulus.json").read_text())
            self.assertNotEqual(tuning["scans"], heldout["scans"], directory.name)
            self.assertEqual(tuning["scan_ms"], heldout["scan_ms"])
            self.assertEqual(set(tuning["scans"][0]), set(heldout["scans"][0]), directory.name)
            self.assertGreater(len(heldout["scans"]), len(tuning["scans"]), directory.name)
            self.assertLess(len(heldout["scans"]), 65535)


if __name__ == "__main__":
    unittest.main()
