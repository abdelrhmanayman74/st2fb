"""The FBs in the controller image are what the st2fb pipeline produces, and the new ST FBs meet the same proof."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

import stack

REPO = stack.EDGE.parent
CONTROLLER = stack.EDGE / "controller"
SCRATCH = stack.EDGE / ".venv" / "pipeline_proof"


def test_generated_fbs_match_pipeline():
    result = subprocess.run([sys.executable, str(CONTROLLER / "gen_fb.py"), "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("name", ["io_guard", "output_pack"])
def test_edge_fb_matches_matiec_on_forte(name):
    """Same proof as the corpus: matiec reference against real FORTE, compared scan by scan."""
    source = CONTROLLER / "st" / name
    out = SCRATCH / name
    out.mkdir(parents=True, exist_ok=True)
    fbt = out / f"{name}.fbt"

    def run(*args):
        result = subprocess.run([sys.executable, "-m", *args], cwd=REPO, capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, result.stdout + result.stderr

    run("st2fb.translate", str(source / "program.st"), "--out", str(fbt))
    run("st2fb.forte_run", "--fbt", str(fbt), "--stimulus", str(source / "stimulus.json"), "--out", str(out / "forte.json"))
    run("st2fb.reference_run", "--st", str(source / "program.st"), "--stimulus", str(source / "stimulus.json"), "--out", str(out / "matiec.json"))
    run("st2fb.compare", str(out / "matiec.json"), str(out / "forte.json"), "--out", str(out / "report.json"))
    report = json.loads((out / "report.json").read_text())
    assert report["equal"] is True, report
    assert report["scans_compared"] > 100
