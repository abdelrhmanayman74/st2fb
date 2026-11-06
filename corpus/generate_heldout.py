#!/usr/bin/env python3
"""Generate corpus/*/heldout_stimulus.json, the stimuli an LLM's final score is taken on.

    python3 corpus/generate_heldout.py

These files are never shown to a model and never used for repair feedback. See docs/LLM.md. Writing
them does not touch any stimulus.json: this script only ever writes heldout_stimulus.json.

A purely random stimulus would rarely reach the deep states of a sequencer, so each one is derived
from the same scenario as the tuning stimulus, with four changes that make it a different test:

1. A separate seed drives the random phases.
2. Every multi-scan hold is jittered, so timers expire and sequences advance at different scans. Single
   scan pulses stay single, because they are what exercises the edge detectors.
3. A closing phase toggles every BOOL and re-chooses numeric inputs among values the scenario has
   already used, so inputs that the scenario changes one at a time now change together.
4. A retune phase holds everything still for long enough that a timer can expire, then raises every
   integer input to the largest value used. The FORTE mutation campaign showed why: on 10_valve_feedback
   no tuning stimulus raises a timer's PT after it has expired, so a real bug there goes unseen.

`python3 -m st2fb.llm.heldout_check` runs them through FORTE and matiec and reports how much the
outputs move, because a held-out stimulus that leaves outputs static proves little.
"""

from __future__ import annotations

import json
import random
from typing import Any

from generate_stimuli import CORPUS, SCENARIOS, Stimulus

HELDOUT_SEED = 104729  # Not the tuning seed, 61499.
FILE_NAME = "heldout_stimulus.json"
CLOSING_SCANS = 300
RETUNE_ROUNDS = 8
RETUNE_MAX_SETTLE = 60
RETUNE_HOLD = 12
HOLD_JITTER = (-1, 0, 0, 1, 2, 3)


class HeldoutStimulus(Stimulus):
    def __init__(self, name: str, scan_ms: int = 10, **defaults: Any) -> None:
        super().__init__(name, scan_ms, **defaults)
        self.rng = random.Random(f"{HELDOUT_SEED}:{name}")
        self.jitter = random.Random(f"{HELDOUT_SEED}:jitter:{name}")

    def hold(self, scans: int = 1, **changes: Any) -> "HeldoutStimulus":
        if scans >= 2:
            scans = max(1, scans + self.jitter.choice(HOLD_JITTER))
        super().hold(scans, **changes)
        return self

    def closing_phase(self, scans: int = CLOSING_SCANS) -> "HeldoutStimulus":
        """Generic random phase over this scenario's own input values."""
        toggle: dict[str, float] = {}
        choose: dict[str, tuple[float, list[Any]]] = {}
        for name, value in self.current.items():
            if isinstance(value, bool):
                toggle[name] = 0.08
            else:
                seen = sorted({scan[name] for scan in self.scans} | {value})
                if len(seen) > 1:
                    choose[name] = (0.03, seen)
        self.random_phase(scans, toggle=toggle, choose=choose)
        return self

    def retune_phase(self, rounds: int = RETUNE_ROUNDS) -> "HeldoutStimulus":
        """Let timers expire at the smallest PT, then raise it while their IN holds."""
        ranges = {}
        for name, value in self.current.items():
            if isinstance(value, int) and not isinstance(value, bool):
                seen = sorted({scan[name] for scan in self.scans})
                if len(seen) > 1:
                    ranges[name] = (seen[0], seen[-1])
        if not ranges:
            return self
        settle = min(RETUNE_MAX_SETTLE, max(high for _, high in ranges.values()) // self.scan_ms + 2)
        for _ in range(rounds):
            for name, value in self.current.items():
                if isinstance(value, bool):
                    self.current[name] = self.rng.random() < 0.5
            self.current.update({name: low for name, (low, _) in ranges.items()})
            Stimulus.hold(self, settle)
            self.current.update({name: high for name, (_, high) in ranges.items()})
            Stimulus.hold(self, RETUNE_HOLD)
        return self


def latch(s: Stimulus) -> None:
    """00_latch has a hand-written tuning stimulus of 7 scans and no scenario, so it gets one here."""
    s.random_phase(200, toggle={"S": 0.2, "R": 0.15})


ALL_SCENARIOS = {"00_latch": (latch, 10, dict(S=False, R=False)), **SCENARIOS}


def build(name: str) -> HeldoutStimulus:
    scenario, scan_ms, defaults = ALL_SCENARIOS[name]
    stimulus = HeldoutStimulus(name, scan_ms, **defaults)
    scenario(stimulus)
    stimulus.closing_phase()
    stimulus.retune_phase()
    return stimulus


def render(stimulus: Stimulus) -> str:
    rows = ",\n".join("  " + json.dumps(scan) for scan in stimulus.scans)
    return f'{{"scan_ms": {stimulus.scan_ms}, "scans": [\n{rows}\n]}}\n'


def main() -> None:
    for name in sorted(ALL_SCENARIOS):
        stimulus = build(name)
        (CORPUS / name / FILE_NAME).write_text(render(stimulus))
        print(f"{name}: {len(stimulus.scans)} scans at {stimulus.scan_ms} ms")


if __name__ == "__main__":
    main()
