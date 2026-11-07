"""Builds prompts from the files in prompt_files/, so that they can be reviewed as plain text.

The system prompt is identical for every program in a run, which is what lets the API cache it. Nothing in
this module can see a held-out stimulus: it receives only the source, a previous attempt, and a failure
description that engine.py wrote from the tuning run.

The prompts of the first benchmark are the ones with no profile, and they must not change, since the disk cache
and that report depend on their exact text. A new prompt is a new file with a version in its name, added here to a
profile: a profile's system prompt is the original text followed by its addenda.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent / "prompt_files"

# Display name, and the file that says how the reference reads the dialect. Generic to the dialect: no per-program text.
DIALECTS = {
    "iec_st_extended": ("IEC 61131-3 Structured Text", "dialect_iec_st_extended_v1.md"),
    "siemens_scl": ("Siemens SCL", "dialect_siemens_scl_v1.md"),
    "rockwell_logix": ("Rockwell Logix structured text", "dialect_rockwell_logix_v1.md"),
}
FORMS = {"ecc_persistent": "form_ecc_persistent_v1.md"}


@dataclass(frozen=True)
class PromptProfile:
    """Which prompt a run uses. The default profile is exactly the first benchmark's prompt."""

    dialect: str | None = None
    form: str | None = None

    def __post_init__(self) -> None:
        if self.dialect is not None and self.dialect not in DIALECTS:
            raise ValueError(f"unknown dialect {self.dialect!r}")
        if self.form is not None and self.form not in FORMS:
            raise ValueError(f"unknown form {self.form!r}")


DEFAULT_PROFILE = PromptProfile()


def _read(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _fill(template: str, **values: str) -> str:
    for name, value in values.items():
        template = template.replace("{{" + name + "}}", value.strip())
    return template


def _addenda(profile: PromptProfile) -> list[str]:
    parts = []
    if profile.dialect is not None:
        parts.append(_read(DIALECTS[profile.dialect][1]))
        parts.append(_read("addendum_hard_v1.md"))
    if profile.form is not None:
        parts.append(_fill(_read(FORMS[profile.form]), EXAMPLE_PERSISTENT_FBT=_read("example_persistent_v1.fbt")))
    return parts


def system_prompt(profile: PromptProfile = DEFAULT_PROFILE) -> str:
    base = _fill(
        _read("system.md"),
        STD_FB_SEMANTICS=_read("std_fb_semantics.md"),
        EXAMPLE_SOURCE=_read("example_source.st"),
        EXAMPLE_FBT=_read("example.fbt"),
    )
    additions = _addenda(profile)
    return base if not additions else base.rstrip("\n") + "\n\n" + "\n".join(additions)


def generate_prompt(source: str, profile: PromptProfile = DEFAULT_PROFILE) -> str:
    if profile.dialect is not None:
        return _fill(_read("generate_dialect_v1.md"), DIALECT_NAME=DIALECTS[profile.dialect][0], SOURCE=source)
    return _fill(_read("generate.md"), SOURCE=source)


def repair_prompt(source: str, previous: str, failure: str) -> str:
    return _fill(_read("repair.md"), SOURCE=source, PREVIOUS=previous, FAILURE=failure)
