"""The register map, loaded from regmap.json. The firmware header is generated from the same file."""
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

_PATH = Path(os.environ.get("ST2FB_REGMAP", Path(__file__).resolve().parent.parent / "regmap.json"))
MAP = json.loads(_PATH.read_text(encoding="utf-8"))
IR = {r["name"]: r for r in MAP["input_registers"]}
HR = {r["name"]: r for r in MAP["holding_registers"]}
TIMING = MAP["timing"]
_WIDTH = {"UINT": 1, "REAL": 2, "DINT": 2}


def span(registers: list[dict]) -> tuple[int, int]:
    """First address and register count covering the given definitions."""
    first = min(r["addr"] for r in registers)
    last = max(r["addr"] + _WIDTH[r["type"]] for r in registers)
    return first, last - first


def group(name: str) -> list[dict]:
    return [r for r in MAP["holding_registers"] if r.get("group") == name]


def decode(registers: list[dict], words: list[int], base: int) -> dict:
    """Named values out of a block of raw 16-bit words that starts at address base."""
    values = {}
    for reg in registers:
        i = reg["addr"] - base
        if i < 0 or i + _WIDTH[reg["type"]] > len(words):
            continue
        if reg["type"] == "UINT":
            values[reg["name"]] = words[i]
        elif reg["type"] == "REAL":
            values[reg["name"]] = struct.unpack(">f", struct.pack(">HH", words[i], words[i + 1]))[0]
        else:
            values[reg["name"]] = struct.unpack(">i", struct.pack(">HH", words[i], words[i + 1]))[0]
    return values


def real_words(value: float) -> list[int]:
    return list(struct.unpack(">HH", struct.pack(">f", value)))
