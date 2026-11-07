"""What reaches a model. Every request of the hard corpus is built offline with sockets blocked, and searched for what must not be in it.

Nothing here can call anything: the only client is the fake one, and socket connections raise. A subprocess such as docker is its own process, so real FORTE and matiec still run.
"""
import json
import re
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from st2fb import fbt, reference_run
from st2fb.llm import benchmark, engine, hard_check, prompts
from st2fb.llm.client import FakeClient, FakeReply, LlmRequest
from st2fb.translate import translate_source

REPO = Path(__file__).resolve().parent.parent
HARD = REPO / "corpus_hard"
PATH_WORDS = re.compile(r"/home/|/tmp/|corpus_hard|\bbuild/|reference\.st|control_flat|control\.fbt|heldout|held-out|pairing_stimulus|stimulus\.json|NOTICE\.md|README", re.IGNORECASE)
# Attribution has to stay out of what a model reads. A public program's licence notice stays, and a request has no other reason to name a project's tooling.
NOT_FOR_A_MODEL = ("AI tooling", "Out of scope", "Solvability control", "Hand-written reference", "never shown to a model")


def _no_network(*args, **kwargs):
    raise AssertionError("a test of what reaches a model tried to open a socket")


def all_cases() -> list[benchmark.Case]:
    return [case for name in hard_check.SETS for case in benchmark.load_set(HARD / name)]


def forbidden_lines(case: benchmark.Case) -> list[str]:
    """Long lines of the files a model must not see, leaving out any line the source it does see also holds."""
    directory = case.tuning_path.parent
    seen = re.sub(r"\s+", " ", case.source)
    lines = []
    for name in ("reference.st", "control_flat.st", "README.md", "NOTICE.md"):
        path = directory / name
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                text = re.sub(r"\s+", " ", line).strip()
                if len(text) >= 25 and text not in seen:
                    lines.append(text)
    return lines


class EveryRequest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(socket.socket, "connect", _no_network)
        patcher.start()
        self.addCleanup(patcher.stop)

    def check_text(self, case: benchmark.Case, text: str) -> None:
        flat = re.sub(r"\s+", " ", text)
        self.assertEqual([word for word in NOT_FOR_A_MODEL if word in text], [])
        matches = [match.group(0) for match in PATH_WORDS.finditer(text)]
        self.assertEqual(matches, [])
        self.assertEqual([line for line in forbidden_lines(case) if line in flat], [])

    def test_every_prompt_of_every_program(self):
        shared_system = {}
        for case in all_cases():
            profile = benchmark.profile_of(case, None)
            system = shared_system.setdefault(profile, prompts.system_prompt(profile))
            for text in (system, prompts.generate_prompt(case.source, profile), prompts.repair_prompt(case.source, "<previous/>", "<failure/>")):
                with self.subTest(case.name):
                    self.check_text(case, text)
            # Numbers from held-out rows would show as JSON. The source and the shared prompts hold no scan rows at all.
            self.assertNotIn('"scan_ms"', prompts.generate_prompt(case.source, profile))

    def test_a_program_input_has_no_way_to_hold_a_held_out_stimulus(self):
        self.assertFalse([field for field in engine.ProgramInput.__dataclass_fields__ if "held" in field.lower()])


class ThroughTheRealPipeline(unittest.TestCase):
    """Replies that fail on purpose, so that the failure text of every kind reaches a request, through real matiec and FORTE."""

    @classmethod
    def setUpClass(cls):
        reference_run.ensure_image()

    def setUp(self):
        patcher = mock.patch.object(socket.socket, "connect", _no_network)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_replies(self, case: benchmark.Case, replies: list[str]) -> list[LlmRequest]:
        requests: list[LlmRequest] = []

        def reply(request: LlmRequest) -> FakeReply:
            requests.append(request)
            return FakeReply(text=replies[len(requests) - 1])

        with tempfile.TemporaryDirectory() as directory:
            benchmark.run_benchmark([case], ["llm_repair"], [("claude-sonnet-5-5", 1)], FakeClient(reply), None, Path(directory), hard={"sets": [case.set_name], "form": None})
        return requests

    def test_failure_text_holds_tuning_inputs_and_nothing_else(self):
        for set_name, name in (("siemens_scl", "s01_conveyor_starter"), ("rockwell_st", "r01_motor_aoi")):
            case = next(c for c in benchmark.load_set(HARD / set_name) if c.name == name)
            good = fbt.write_fbt(translate_source(case.oracle))
            # A wrong output, a compile failure, then an invalid file, which uses up the repair attempts.
            first = re.sub(r"(<Algorithm Name=\"scan\">\s*<ST><!\[CDATA\[)", r"\1\n", good)
            wrong_output = re.sub(r"(\]\]></ST>\s*</Algorithm>\s*</BasicFB>)", lambda m: "\nDOES_NOT_EXIST := 1;\n" + m.group(1), first)
            different = good.replace(":= TRUE;", ":= FALSE;", 1)
            self.assertNotEqual(different, good)
            requests = self.run_replies(case, [different, wrong_output, "not an fbt"])
            self.assertEqual(len(requests), 3)
            tuning_rows = {json.dumps(scan) for scan in json.loads(case.tuning_path.read_text(encoding="utf-8"))["scans"]}
            held_rows = {json.dumps(scan) for path in case.heldout_paths for scan in json.loads(path.read_text(encoding="utf-8"))["scans"]} - tuning_rows
            for request in requests:
                text = request.system + request.user
                with self.subTest(name):
                    self.assertEqual([row for row in held_rows if row in text], [])
                    self.assertEqual([word for word in NOT_FOR_A_MODEL if word in text], [])
                    # The candidate repeated in a repair prompt is this test's own reply, which holds no path. The source holds none either.
                    self.assertEqual([m.group(0) for m in PATH_WORDS.finditer(text)], [])
                    self.assertEqual([line for line in forbidden_lines(case) if line in re.sub(r"\s+", " ", request.system + prompts.generate_prompt(case.source, benchmark.profile_of(case, None)))], [])
            self.assertIn("Inputs on the scans leading to it:", requests[1].user)


if __name__ == "__main__":
    unittest.main()
