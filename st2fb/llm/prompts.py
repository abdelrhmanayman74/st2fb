"""Builds prompts from the files in prompt_files/, so that they can be reviewed as plain text.

The system prompt is identical for every program, which is what lets the API cache it. Nothing in
this module can see a held-out stimulus: it receives only the source, a previous attempt, and a failure
description that engine.py wrote from the tuning run.
"""
from __future__ import annotations

from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent / "prompt_files"


def _read(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _fill(template: str, **values: str) -> str:
    for name, value in values.items():
        template = template.replace("{{" + name + "}}", value.strip())
    return template


def system_prompt() -> str:
    return _fill(
        _read("system.md"),
        STD_FB_SEMANTICS=_read("std_fb_semantics.md"),
        EXAMPLE_SOURCE=_read("example_source.st"),
        EXAMPLE_FBT=_read("example.fbt"),
    )


def generate_prompt(source: str) -> str:
    return _fill(_read("generate.md"), SOURCE=source)


def repair_prompt(source: str, previous: str, failure: str) -> str:
    return _fill(_read("repair.md"), SOURCE=source, PREVIOUS=previous, FAILURE=failure)
