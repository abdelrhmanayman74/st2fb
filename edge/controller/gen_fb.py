#!/usr/bin/env python3
"""Regenerate controller/generated/ from ST with the repo's own pipeline.

    python3 edge/controller/gen_fb.py          # rewrite the generated C++
    python3 edge/controller/gen_fb.py --check  # exit 1 if the checked-in C++ is out of date

The image build copies generated/ and does not import st2fb, so the build context is edge/ alone.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

from st2fb import export_forte, fbt, translate  # noqa: E402

SOURCES = {
    "PUMP_STATION_SUPERVISOR": REPO / "corpus/20_pump_station_supervisor/program.st",
    "IO_GUARD": HERE / "st/io_guard/program.st",
    "OUTPUT_PACK": HERE / "st/output_pack/program.st",
}
OUT = HERE / "generated"


def generate() -> dict[str, str]:
    files: dict[str, str] = {}
    for name, source in SOURCES.items():
        fb = translate.translate_source(source.read_text(encoding="utf-8"))
        if fb.name != name:
            raise SystemExit(f"{source}: expected {name}, got {fb.name}")
        files[f"{name}.fbt"] = fbt.write_fbt(fb)
        files.update(export_forte.export_fb(fb))
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = generate()
    if args.check:
        stale = [n for n, text in files.items() if not (OUT / n).exists() or (OUT / n).read_text(encoding="utf-8") != text]
        if stale:
            print("out of date:", ", ".join(stale))
            return 1
        print(f"generated/ matches the pipeline ({len(files)} files)")
        return 0
    OUT.mkdir(exist_ok=True)
    for name, text in files.items():
        (OUT / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(files)} files to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
