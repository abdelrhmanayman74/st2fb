#!/usr/bin/env python3
"""Estimate what a live run on corpus_hard/ would likely cost, from the tokens the first benchmark measured.

    python3 scripts/estimate_hard_cost.py

THIS IS AN ESTIMATE, NOT A MEASUREMENT, AND NOT A LIMIT. Budget safety comes from --budget-usd and the dry run's worst case. Nothing here calls anything.

Method. From results/benchmark_2026-11-06/benchmark.json, read-only:
- Output tokens per byte of the deterministic translator's .fbt for that program, per model, over first attempts. A migration's size is close to
  that of the translation of a flat equivalent, and for corpus_hard/ that is the file the solvability control comes from.
- Input tokens per byte of prompt.
Each scenario then applies a price table to these. The system prompt is one cache write per dialect and then cache reads, as in the first run.

    low    every program passes on its first attempt, at the measured output per byte
    high   every program uses all 3 attempts of llm_repair, each with twice the measured output per byte, up to max_tokens

The hard programs are harder, so thinking may take more than the first benchmark's ratio. That is why the two are far apart.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from st2fb import fbt  # noqa: E402
from st2fb.llm import benchmark, hard_check, prompts  # noqa: E402
from st2fb.llm.config import PRICES  # noqa: E402
from st2fb.translate import translate_source  # noqa: E402

MODELS = ("claude-sonnet-5-5", "claude-opus-5-5")
EARLIER = REPO / "results" / "benchmark_2026-11-06" / "benchmark.json"


def fbt_bytes(source: str) -> int:
    return len(fbt.write_fbt(translate_source(source)).encode("utf-8"))


def measured() -> tuple[dict[str, float], float]:
    document = json.loads(EARLIER.read_text(encoding="utf-8"))
    per_byte: dict[str, list[float]] = {model: [] for model in MODELS}
    input_ratio = []
    cases = {case.name: case for case in benchmark.load_cases(REPO / "corpus", ["all"])}
    system_bytes = len(prompts.system_prompt().encode("utf-8"))
    for row in document["results"]:
        if row["mode"] != "llm_only" or row["model"] not in per_byte or row["attempts"] != 1:
            continue
        case = cases[row["program"]]
        per_byte[row["model"]].append(row["output_tokens"] / fbt_bytes(case.source))
        prompt_bytes = system_bytes + len(prompts.generate_prompt(case.source).encode("utf-8"))
        input_ratio.append(row["input_tokens"] / prompt_bytes)
    return {model: statistics.mean(values) for model, values in per_byte.items()}, statistics.mean(input_ratio)


def control_bytes(case: benchmark.Case, directory: Path) -> int:
    text = hard_check.control_source(case, directory)
    return fbt_bytes(text if text is not None else case.source)


def estimate(cases: list[tuple[benchmark.Case, int]], model: str, form: str | None, per_byte: dict[str, float], ratio: float, max_tokens: int | None) -> tuple[float, float, int]:
    price = PRICES[model]
    low = high = 0.0
    largest = 0
    written = set()
    for case, size in cases:
        profile = benchmark.profile_of(case, form)
        system_tokens = len(prompts.system_prompt(profile).encode("utf-8")) * ratio
        user_tokens = len(prompts.generate_prompt(case.source, profile).encode("utf-8")) * ratio
        output = size * per_byte[model]
        largest = max(largest, round(output))
        first_input = (system_tokens * price.cache_read + user_tokens * price.input) / 1e6
        if profile not in written:
            written.add(profile)
            first_input = (system_tokens * price.cache_write + user_tokens * price.input) / 1e6
        low += first_input + output * price.output / 1e6
        heavy = min(2 * output, benchmark.tokens_for(case, max_tokens))
        repair_user = user_tokens + heavy + 1000
        high += first_input + heavy * price.output / 1e6
        high += 2 * ((system_tokens * price.cache_read + repair_user * price.input) / 1e6 + heavy * price.output / 1e6)
    return low, high, largest


def main() -> int:
    per_byte, ratio = measured()
    print("ESTIMATE ONLY. From the first benchmark's tokens, and not a measurement of these programs.")
    print(f"Measured: output tokens per .fbt byte {({k: round(v, 3) for k, v in per_byte.items()})}, input tokens per prompt byte {ratio:.3f}.")
    sets = {name: benchmark.load_set(hard_check.HARD / name) for name in hard_check.SETS}
    plans: dict[str, tuple[list[tuple[benchmark.Case, int]], str | None]] = {}
    for name, cases in sets.items():
        plans[name] = ([(case, control_bytes(case, hard_check.HARD / name / case.name)) for case in cases], None)
    ecc = benchmark.load_cases(REPO / "corpus", list(benchmark.ECC_PERSISTENT_PROGRAMS))
    plans["ecc_persistent (control .fbt size)"] = (
        [(case, len((hard_check.HARD / "ecc_persistent" / case.name / "control.fbt").read_bytes())) for case in ecc], "ecc_persistent",
    )
    total = {model: [0.0, 0.0] for model in MODELS}
    print(f"{'set':38} {'programs':>8} {'model':20} {'low USD':>8} {'high USD':>9} {'largest first reply, tokens':>28}")
    for name, (cases, form) in plans.items():
        for model in MODELS:
            low, high, largest = estimate(cases, model, form, per_byte, ratio, None)
            total[model][0] += low
            total[model][1] += high
            print(f"{name:38} {len(cases):8d} {model:20} {low:8.2f} {high:9.2f} {largest:28d}")
    for model in MODELS:
        print(f"ALL, one repeat of llm_repair: {model}: {total[model][0]:.2f} to {total[model][1]:.2f} USD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
