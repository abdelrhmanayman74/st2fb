# LLM migration layer

The model proposes a Basic FB. It never decides correctness. Its `.fbt` goes through the same exporter, FORTE
build, matiec reference and `st2fb.compare` as the deterministic translator's.

**One live run exists, on `corpus/` only, in `results/benchmark_2026-11-06/`.** A human approved it, and its report and candidates are kept there, read-only. **No model has run on `corpus_hard/`.** Everything
said of that corpus in `docs/HARD_CORPUS.md` comes from the translator, matiec, FORTE and scripted fake replies. The tests use fake clients and a stub HTTP server on localhost, and they send nothing to Anthropic.

## Layout

| File | Purpose |
|---|---|
| `st2fb/llm/config.py` | Model choice, the one price table, cost from usage, worst-case cost |
| `st2fb/llm/keys.py` | Reads the key from `.env`, and redacts it |
| `st2fb/llm/client.py` | Request and response types, typed errors, `FakeClient` |
| `st2fb/llm/live_client.py` | The only module that imports the SDK |
| `st2fb/llm/budget.py` | The spend ledger |
| `st2fb/llm/cache.py` | The disk cache |
| `st2fb/llm/gateway.py` | Every request: cache, then budget check, then client |
| `st2fb/llm/engine.py` | Generate and repair, on the tuning stimulus only |
| `st2fb/llm/benchmark.py` | The CLI, held-out scoring, reports |
| `st2fb/llm/heldout_check.py` | Checks the held-out stimuli with the deterministic translator |
| `st2fb/llm/prompts.py`, `st2fb/llm/prompt_files/` | The prompts, as plain files |
| `corpus/generate_heldout.py` | Generates `corpus/*/heldout_stimulus.json` |
| `st2fb/llm/ecc_metric.py` | The strict `ecc_persistent` metric. See `docs/HARD_CORPUS.md` |
| `st2fb/llm/hard_check.py` | Checks `corpus_hard/` with no model: both deterministic tiers, oracle, solvability controls |
| `st2fb/llm/manifest.py` | The hash of what `hard_check` passed on. A real benchmark on `corpus_hard/` refuses to run without a match |
| `st2fb/vendor_frontend.py` | A small syntax rewrite of the vendor dialects, the `frontend+translator` comparator. See `docs/HARD_CORPUS.md` |
| `st2fb/forte_eval.py` | Judges any `.fbt` on FORTE. Shared with the mutation campaign |

The core pipeline needs only the standard library. A test imports it under `python3 -S` and checks that the SDK
was not loaded. The SDK goes in a repo-local venv:

    python3 -m venv .venv && .venv/bin/pip install -r requirements-llm.txt

`requirements-llm.txt` pins `anthropic==2.6.0`, the version installed and tested. The skill's Python README still
describes `anthropic` 1.x, so the request shape was also checked against the 2.6.0 signatures and is pinned by
`tests/test_llm_live_client.py`, which runs the real SDK against the stub server. One visible difference: this SDK
sends an API key as `Authorization: Bearer` under API version `2026-10-21`, and not as `x-api-key`.

## Model, effort, prices

- Default model `claude-sonnet-5-5`. `claude-opus-5-5` is also allowed. Nothing else is accepted.
- Effort is always sent, as `output_config.effort`, default `medium`. That is the skill's starting point for coding work on
  Sonnet 5.5 (whose API default is `high`) and the API default on Opus 5.5. Sending it means a change to an API default
  cannot change results silently. It is part of the cache key.
- `max_tokens` defaults to 16000. Thinking counts toward it. The largest deterministic `.fbt` in the corpus is 8.4 kB, about
  3000 tokens at a rough guess, so this leaves room, but only a live run will show whether it leaves enough. A truncated reply
  is reported as the category `max_tokens`. The cap is 21333, above which SDK 2.6.0 refuses a non-streaming request.
- No `temperature`, `top_p`, `top_k` or `thinking`: per the skill, the sampling parameters return a 400 on Opus 5.5 and
  thinking is controlled through effort.

| Model | Input | Output | Cache write (5 min) | Cache read |
|---|--:|--:|--:|--:|
| claude-sonnet-5-5 | $2.00 | $10.00 | $2.50 | $0.20 |
| claude-opus-5-5 | $4.00 | $20.00 | $5.00 | $0.20 |
| claude-sonnet-5 (fallback only) | $2.00 | $10.00 | $2.50 | $0.20 |
| claude-opus-5, claude-opus-4-8 (fallback only) | $5.00 | $25.00 | $6.25 | $0.50 |

USD per million tokens, **as cached in the skill on 2026-10-06**, in one table in `config.py`. They may be out of date.
Tokens come from `response.usage`, and cost is those tokens times this table, so the figures are estimates until checked against
the Console. A model missing from the table is charged at the dearest rate rather than at nothing.

The system prompt is identical for every program and carries `cache_control`, so repeated requests can read it from the
API's prompt cache. That is separate from the disk cache below.

## Stop reasons

`stop_reason` is checked before the content is read.

- `refusal`: category `refusal`, with `stop_details.category` recorded. Not repaired: it would likely decline again, at a cost.
- `max_tokens`: category `max_tokens`. The truncated text is not evaluated, and it is not repaired, since the same limit would
  most likely cut it off again. Raise `--max-tokens` instead.
- Anything else other than `end_turn`: category `bad_stop_reason`. This request has no tools, so none is expected.

## Server-side fallback: what the skill says and what was done

The skill says that the classifiers on these models can decline benign requests, that a request without a fallback simply stops,
and to ship the opt-in from day one and tell the user. Checked against this request shape:

- `fallbacks: "default"` with beta `server-side-fallback-2026-07-01` is the recommended form, and `client.beta.messages.create`
  in 2.6.0 accepts it. The request is a single user turn with no tools, not streamed, on the Claude API, so it is
  compatible: no thinking blocks are echoed back, which is what makes the multi-turn case awkward.
- It is rejected on the Batches API, which is one reason batch mode is skipped.

So it is **on by default**, and `--no-fallbacks` turns it off. Three consequences are handled:

1. **Cost.** Top-level `usage` covers only the attempt that produced the message. `usage.iterations` has every attempt, each billed
   at its own model's rate, and that is what the live client reads.
2. **The worst case doubles.** A decline can come after the first model used all its output, and then a fallback model runs too, and on
   Opus 5.5 that model can cost more ($5/$25). `worst_case_usd` counts both attempts. It assumes one hop, which the skill's
   description of `"default"` implies and does not state outright.
3. **The answer may not be from the requested model.** Per the skill, Sonnet 5.5's fallback covers `cyber` and `frontier_llm` declines and
   runs on Sonnet 5. So reports have `served_by` and `fell_back` on every row and a `Fell back` count in the aggregate. A score that
   includes fallback runs is not purely that model's score. For a strict comparison, check that the count is zero or use `--no-fallbacks`.

## Key handling

- Only `ST2FB_ANTHROPIC_API_KEY` is read, by a small parser in `keys.py`, from `.env` or `--env-file`, and only on the `--live` path.
- It is passed as `Anthropic(api_key=...)`. `ANTHROPIC_API_KEY` is neither read nor set. Per the SDK's docstring an explicit key means
  the environment is not consulted for credentials, and a test confirms this with those variables set to other values.
- `base_url` is passed explicitly too, so that a stray `ANTHROPIC_BASE_URL` cannot send the key somewhere else.
- API errors are rebuilt as safe messages with the key redacted, and raised `from None`. Tests make a stub server echo a fake key in
  a 401 and a 500, and then search stdout, stderr and every file under the output directory for it.
- Not covered: `ANTHROPIC_LOG=debug` turns on the SDK's own logging, which this project does not control. Do not set it on a live run.

## Modes

Both produce an `.fbt` that goes through the unchanged pipeline.

- `llm_only`: one attempt.
- `llm_repair`: up to 3 attempts. Each repair prompt holds the source, the previous `.fbt` and the concrete failure: the XML or schema
  error, the exporter or g++ error, the missing-CNF or crash message, or the first divergence with the inputs on the scans leading to it.
  It is one user message rather than a conversation, which keeps repairs independent of thinking-block replay rules.

Failure categories: `xml_error`, `interface_error`, `compile_error`, `runtime_error`, `tuning_different`, `heldout_different`, `refusal`,
`max_tokens`, `bad_stop_reason`, `infra_error`, `api_error`, `budget_stop`, `not_run`. An `infra_error` means Docker or FORTE start-up failed twice. It
gets no repair prompt, because the model did nothing wrong.

## Prompts

`st2fb/llm/prompt_files/`: `system.md`, `generate.md`, `repair.md`, `std_fb_semantics.md`, `example_source.st`, `example.fbt`. They ask for an idiomatic Basic FB:
CASE state machines become real EC states where sensible, REQ carries every input, CNF carries every output, per the contract in `docs/DESIGN.md`.

- `std_fb_semantics.md` is the translator's `STD_FBS`, which come from matiec's library. A test fails if the two drift apart. The model is told the
  semantics because matching them is part of the job, and the corner cases would otherwise have to be guessed.
- `example.fbt` is a state machine that is not in the corpus. A test runs it on real FORTE against matiec, so the prompt cannot teach a bug.

## Idiomatic structure

Every row records `ecc_states`, `working_states` (states with at least one action) and `algorithms`. `restructured` means two or more working states. So
a one-state wrapper, `START -> RUN -> START`, reports as `restructured: false` even if it is correct, and `source_has_case` shows whether restructuring was
even sensible. A correct wrapper on a program with no state machine is the right answer, not a failure. This counts states, and says nothing about
whether they are good states. A model could add a state to pass the test, so a human should read the candidates, which are kept under
`candidates/<model>/<program>/`.

## Overfitting

Repair feedback uses only the tuning stimulus, `stimulus.json`. The final score uses `heldout_stimulus.json`, which the model never sees.

- `engine.py` is given only the tuning path and trace. `ProgramInput` has no held-out field, and a test checks that neither the engine nor any prompt mentions it.
- Scoring happens in `benchmark.py`, after the engine returned, and nothing it computes goes back to a model. A candidate that passes tuning and fails held-out gets no
  repair and scores as failed, category `heldout_different`.
- `passed` needs both stimuli equal.

The held-out stimuli come from `corpus/generate_heldout.py`, seed 104729 (tuning is 61499), and it writes only `heldout_stimulus.json`. Each uses the program's tuning scenario
with jittered holds, a new random seed, a closing phase of 300 scans that toggles every BOOL and re-chooses numeric inputs, and a retune phase that lets timers expire and then raises
their PT while IN holds. `00_latch` has no scenario, so it gets a random one.

`python3 -m st2fb.llm.heldout_check` was run, with the deterministic translator as the control:

- **21/21 equal between FORTE and matiec on held-out.**
- **No output is static on held-out**, and none is on tuning, so there is no exception to report.
- No held-out stimulus equals its tuning stimulus. A test also regenerates all 20 generated tuning files in memory and compares bytes, and `sha256sum` of all 21 `stimulus.json` was the
  same before and after.

Limits to keep in mind:

- It is not independent of tuning, since it comes from the same scenario by the same author. It tests different timing and combinations, not a different idea of what the program is for.
- The first scans can be identical: the shared prefix is 1 to 85 scans, because single-scan steps are not jittered.
- `18_pump_station_rotation` has fewer output changes on held-out (1427) than on tuning (1809), though it has more scans. Every other program has at least as many.
- Repeated use of a held-out set by people, as opposed to models, wears it out too: anyone who tunes the prompts by looking at held-out failures is overfitting by hand.

## Budget safety

- Live calls need both `--live` and a positive `--budget-usd`. Without `--live`, the code that builds a live client is not called, and a test makes it raise to prove this.
- `--dry-run` prints the plan and the worst case, reads no key, runs no Docker and calls nothing, even if `--live` is also given.
- Before each request, `Ledger.reserve` refuses if spend has reached the cap, or if spend plus this request's worst case would exceed it.
- The worst case takes one input token per UTF-8 byte at the cache-write rate, plus all of `max_tokens`, for both the model and its fallback. This deliberately overstates, so a small budget can stop early with money unspent.
- `build/llm/ledger.jsonl` is append-only and synced to disk. A reservation is written before the request and settled afterwards. **The cap is cumulative across runs**: `--budget-usd 5` means five dollars
  in total in this ledger, not five more.
- If the process dies mid-request, or a connection drops, the reservation stays open and counts at its worst case. Nobody knows whether the server ran it, so spend can be overestimated, and it is not knowingly underestimated. To correct one after checking the Console, append a `settle` line with that reservation's `id` and the real cost.
- The SDK runs with `max_retries=0`, so that one SDK call is one HTTP request the ledger can see. `gateway.py` retries a 429, a 5xx or a lost connection up to twice, checking the budget each time. Status errors release their reservation, on the assumption that an error response
  is not billed.
- A stop exits with status 3 for budget and 4 for API errors, and the report says why. The spend so far stays in the report, and a rerun picks up from the disk cache.

## Disk cache

`build/llm/cache/`, keyed on client kind, model, effort, `max_tokens`, fallback setting, system prompt hash, user prompt hash, input hash, repeat index and attempt. Refusals and truncated replies are cached too, since they were paid for. Errors are not. It holds
the response and its usage, and no credential. The repeat index is in the key because repeats must be independent samples, so repeat 1 is never served repeat 0's answer. A report's `cost_usd` is what the response cost when it was made, and `new_spend_usd` is what this run paid.

The mode is deliberately **not** in the key. `llm_only` and `llm_repair` send an identical first prompt, so within a repeat they share one first response. That saves the price of one request per program and repeat, and it makes the modes paired samples: repair is measured on the same first draft, so `llm_repair` can only do as well as or better than `llm_only` on tuning. It does mean the two are not independent, and the Markdown report says so. Adding the mode to the key in `cache.py` would make them independent, at that extra cost.

## Benchmark

    python3 -m st2fb.llm.benchmark --dry-run --model claude-sonnet-5-5:3 claude-opus-5-5:1
    python3 -m st2fb.llm.benchmark --programs 00_latch                    # fake client, no key, no network
    .venv/bin/python -m st2fb.llm.benchmark --live --budget-usd 1 --programs 00_latch --modes llm_only

Options: `--programs` (names or `all`), `--modes`, `--repeats`, `--model` (one or more `MODEL` or `MODEL:REPEATS`), `--effort`, `--max-tokens`, `--no-fallbacks`, `--budget-usd`, `--live`, `--dry-run`, `--env-file`, `--corpus`, `--out-dir`, `--corpus-dir`, `--form`. The last two select the hard corpus, its prompts and its report format, and have their own reports, ledger and cache under `build/llm_hard/`. There, `--max-tokens` overrides a program's setting recorded in its `set.json`, and each held-out file of a program is scored. See `docs/HARD_CORPUS.md`. Without them the prompts, cache keys and report format are those of the first benchmark.

The published run in `results/benchmark_2026-11-06/` used `--no-fallbacks`, which is part of the cache key.

Requests run one at a time. Reports go to `benchmark.json` and `benchmark.md`, per program, mode and repeat: tuning equal, held-out equal, passed, attempts, tokens, cost, ECC states, failure category. They also have the deterministic baseline, and an aggregate with cost per run that passes held-out. A rerun overwrites the report and rebuilds it from the cache at no cost.

`build/forte_cache` is pruned to 3 GB after each run, oldest first, since each candidate's FORTE is 24 MB.

### Fake results cannot pass for real ones

Without `--live` the output directory is `build/llm/fake/`, and `run_benchmark` refuses to write fake results to `build/llm/`. Every report, row, ledger line and cache entry has `"client": "fake"`, the Markdown opens with a banner, and the client kind is in the cache key, so a fake entry can never be replayed as live. The default fake client echoes the deterministic translator, so its rows say nothing about any model.

## Batch mode

Skipped. It is optional, `fallbacks` is rejected on the Batches API, and repair is a feedback loop that a batch cannot run. `llm_only` could use it at half price if cost becomes the constraint.

## Tests

    python3 -m unittest tests.test_llm_unit tests.test_llm_e2e        # needs Docker for e2e, not for unit
    .venv/bin/python -m unittest tests.test_llm_live_client           # needs the SDK, and Docker for two of them
    python3 -m unittest tests.test_fbt_campaign                       # the mutation campaign and st2fb.forte_eval

No test uses the real key or a real API. `test_llm_e2e.py` runs each scenario through real FORTE and matiec with scripted responses, made from translator and mutator output. `test_llm_live_client.py` runs the real SDK against a stub on 127.0.0.1 with a fake key, and labels its results fake.

## Before the first live run

1. `python3 -m st2fb.llm.benchmark --dry-run --programs 00_latch --modes llm_only`.
2. A human approves it, and checks the prices against the current price list.
3. `.venv/bin/python -m st2fb.llm.benchmark --live --budget-usd 1 --programs 00_latch --modes llm_only`.
4. Check `build/llm/ledger.jsonl` against the Console, before spending any more.
