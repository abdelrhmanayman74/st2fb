"""Judge one piece of .fbt text against a reference trace on real FORTE, and say how it went.

The mutation campaign and the LLM layer both need the same answer, and both must tell "this FB is
wrong" apart from "this FB did not compile", so that lives here. It adds no judgement of its own: it
calls the parser, the exporter, forte_run and compare, and only sorts their failures into statuses.

Statuses, in pipeline order:
    parse_failed     not well-formed XML, or not an FBType (fbt.parse_fbt)
    plan_failed      breaks the contract: no REQ or CNF, interface does not fit the stimulus
    compile_failed   rejected by the exporter's type checks, or by g++
    timed_out        ran, but some REQ never produced a CNF within the scan limit
    crashed          FORTE or the driver died
    infra_failed     Docker or FORTE start-up failed twice: says nothing about the FB
    different        ran to the end, and the trace differs from the reference
    equal            ran to the end, and the trace matches
"""
from __future__ import annotations

import functools
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import compare, fbt, forte_run

REPO_ROOT = forte_run.REPO_ROOT
# Each scan has its own limit inside forte_run. This one only catches a stuck Docker.
HARD_LIMIT_S = 900
_DETAIL_LIMIT = 4000
CACHE_LIMIT_BYTES = 3 * 1024**3  # The project's limit is 5 GB, including everything else under build/.
_INFRA_MARKERS = ("did not open port", "Cannot connect to the Docker daemon", "docker: Error", "docker: ")


@dataclass(frozen=True)
class Outcome:
    status: str
    detail: str = ""
    report: dict[str, Any] | None = None  # compare's report, when the run reached the end
    binary_dir: Path | None = None  # where the compiled FORTE is, for a caller that prunes it

    @property
    def equal(self) -> bool:
        return self.status == "equal"


@functools.lru_cache(maxsize=1)
def _image_id() -> str:
    return forte_run.ensure_image()


def prune_cache(limit_bytes: int = CACHE_LIMIT_BYTES, cache_dir: Path | None = None) -> int:
    """Delete the oldest compiled FORTEs until the cache fits. Returns how many went.

    Each is about 24 MB. Deleting one is safe, since the next run of that FB just compiles it again.
    Not for use while another thread is evaluating, which could lose a binary it just built.
    """
    cache_dir = cache_dir or forte_run.CACHE_DIR
    if not cache_dir.exists():
        return 0
    entries = []
    for entry in cache_dir.iterdir():
        if entry.is_dir() and not entry.name.startswith("tmp-"):
            size = sum(path.stat().st_size for path in entry.iterdir() if path.is_file())
            entries.append((entry.stat().st_mtime, size, entry))
    total = sum(size for _, size, _ in entries)
    removed = 0
    for _, size, entry in sorted(entries, key=lambda item: item[0]):
        if total <= limit_bytes:
            break
        shutil.rmtree(entry, ignore_errors=True)
        total -= size
        removed += 1
    return removed


def trim_compiler_output(text: str, limit: int = _DETAIL_LIMIT) -> str:
    """The error lines of a g++ log, not its pages of template context."""
    errors = [line for line in text.splitlines() if " error: " in line or line.startswith("FAILED")]
    kept = "\n".join(errors) if errors else text
    return kept[:limit]


def _run_on_forte(fbt_path: Path, stimulus_path: Path, out: Path, scan_timeout: float) -> tuple[int, str]:
    command = [
        sys.executable, "-m", "st2fb.forte_run", "--fbt", str(fbt_path), "--stimulus", str(stimulus_path),
        "--out", str(out), "--scan-timeout", str(scan_timeout),
    ]  # fmt: skip
    try:
        result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=HARD_LIMIT_S)
    except subprocess.TimeoutExpired:
        return 124, f"no result within {HARD_LIMIT_S} s"
    return result.returncode, result.stderr


def evaluate(
    fbt_text: str,
    stimulus_path: Path,
    reference: dict[str, Any],
    scan_timeout: float = 5.0,
    keep_dir: Path | None = None,
) -> Outcome:
    """Run fbt_text on FORTE with this stimulus and compare with the reference trace.

    keep_dir, if given, receives the trace as forte.json and FORTE's log. Otherwise nothing is kept.
    """
    try:
        fb = fbt.parse_fbt(fbt_text)
    except (ValueError, TypeError) as exc:
        return Outcome("parse_failed", str(exc))

    try:
        forte_run.build_plan(fb, json.loads(stimulus_path.read_text(encoding="utf-8")))
    except forte_run.RunError as exc:
        return Outcome("plan_failed", str(exc))

    try:
        binary_dir = forte_run.compile_fb(fb, _image_id())
    except forte_run.RunError as exc:
        return Outcome("compile_failed", trim_compiler_output(str(exc)))
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        # ExportError is the expected one. Any other is the exporter choking on odd input, which is
        # still this FB's rejection and must not end a whole campaign.
        return Outcome("compile_failed", f"{type(exc).__name__}: {exc}"[:_DETAIL_LIMIT])

    forte_run.RUN_DIR.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="eval-", dir=forte_run.RUN_DIR))
    try:
        fbt_path, out = work / f"{fb.name}.fbt", work / "forte.json"
        fbt_path.write_text(fbt_text, encoding="utf-8")
        code, stderr = _run_on_forte(fbt_path, stimulus_path, out, scan_timeout)
        if code != 0 and any(marker in stderr for marker in _INFRA_MARKERS):
            code, stderr = _run_on_forte(fbt_path, stimulus_path, out, scan_timeout)
            if code != 0 and any(marker in stderr for marker in _INFRA_MARKERS):
                return Outcome("infra_failed", stderr[-_DETAIL_LIMIT:], binary_dir=binary_dir)
        if keep_dir is not None:
            keep_dir.mkdir(parents=True, exist_ok=True)
            for path in (out, out.with_name(out.name + ".log")):
                if path.exists():
                    shutil.copyfile(path, keep_dir / path.name)
        if code == 124 or "no CNF within" in stderr:
            return Outcome("timed_out", stderr[-_DETAIL_LIMIT:], binary_dir=binary_dir)
        if code != 0:
            return Outcome("crashed", stderr[-_DETAIL_LIMIT:], binary_dir=binary_dir)
        report = compare.compare_traces(reference, compare.load_trace(out))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return Outcome("equal" if report["equal"] else "different", report=report, binary_dir=binary_dir)
