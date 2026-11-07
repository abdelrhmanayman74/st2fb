"""Which files a hard_check pass was about, so that a benchmark cannot run on files nobody checked.

`python3 -m st2fb.llm.hard_check` records a hash of everything it depends on when it passes. A real benchmark on corpus_hard/ recomputes
the hash and refuses to start if it differs, or if no pass is on record. The hash covers every program file of every set, the set
settings, the four programs and controls of the ecc_persistent set, and the prompt files. No model reply or result file is in it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
HARD = REPO / "corpus_hard"
PROMPTS = Path(__file__).resolve().parent / "prompt_files"
RECORD = REPO / "build" / "llm_hard" / "hard_check.json"
ECC_PROGRAMS = ("06_star_delta", "13_case_sequencer", "14_batch_filling", "20_pump_station_supervisor")


class NotChecked(RuntimeError):
    """hard_check has not passed on these files."""


def files() -> list[Path]:
    found = [path for set_dir in HARD.iterdir() if set_dir.is_dir() and set_dir.name != "__pycache__" for path in set_dir.rglob("*") if path.is_file()]
    found += [path for path in PROMPTS.iterdir() if path.is_file()]
    for name in ECC_PROGRAMS:
        found += [REPO / "corpus" / name / file for file in ("program.st", "stimulus.json", "heldout_stimulus.json")]
    return sorted(found)


def compute() -> str:
    digest = hashlib.sha256()
    for path in files():
        digest.update(path.relative_to(REPO).as_posix().encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def require_passed(record: Path = RECORD) -> None:
    if not record.exists():
        raise NotChecked(f"{record} does not exist. Run python3 -m st2fb.llm.hard_check first.")
    document = json.loads(record.read_text(encoding="utf-8"))
    if not document.get("passed"):
        raise NotChecked("the last hard_check did not pass on the whole corpus. Run python3 -m st2fb.llm.hard_check.")
    if document.get("manifest") != compute():
        raise NotChecked("corpus or prompt files changed since hard_check passed. Run python3 -m st2fb.llm.hard_check again.")
