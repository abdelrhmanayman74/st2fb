# Hard corpus

The first benchmark passed almost everywhere, and the free deterministic translator also passed 21 of 21. So that corpus cannot show what a model adds. `corpus_hard/` holds programs the current translator's parser cannot read, with the oracle kept independent of the model. **No live model run has been made on this corpus. Everything below comes from the translator, a small syntax front-end, matiec, FORTE and scripted fake replies.**

A model failing here is a useful result. Tests and prompts were not tuned to make a model look good, and no prompt holds a per-program answer.

## What a pass here would and would not show

Of the 23 programs, the translator rejects 21. A pass by a model on one of those means this, and only this:

> The model produced an FB equal to matiec's run of the reference on these stimuli, using the dialect's stated semantics, where the current translator's parser stops. 12 of these programs fall to a small syntax front-end, and the others need ordinary compiler work (flattening and inlining). This does not show the model can do what deterministic code cannot, that it knows vendor semantics, or that the FB matches a real S7 or Logix controller.

- **There are two deterministic comparators, and a report compares a pass with both.** `translator` is the current translator on what the model sees. `frontend+translator` puts `st2fb/vendor_frontend.py` in front of it. That is under 300 lines of regular expressions written from the dialect prompts, with no parser and no type checker, and it never reads `reference.st`. It gets 12 of the 21 rejected programs to pass on real FORTE against matiec on every scored stimulus. The other 9 use arrays, helper blocks or functions, and it does not flatten or inline them. That work is ordinary compiler work, and no attempt was made to write it.
- **The corpus is mostly self-authored.** The same project wrote these programs, stimuli and prompts, apart from `public_st`. `corpus_hard/stress/x01_pump_station` and all the Siemens and Rockwell programs were written by this project's AI tooling. None comes from a plant.
- **Passing says the traces match on these stimuli.** Mutation numbers below say how much those stimuli notice, and there is no proof beyond that.

## Sets

| Set | What it is | Programs | What the model sees | What matiec runs |
|---|---|--:|---|---|
| `unsupported_st` | Self-authored plain ST outside the translator's scope | 6 | `program.st` | the same `program.st` |
| `siemens_scl` | **TIA-style, never compiled, judged by matiec readings** | 8 | `program.scl` only | hand-written `reference.st` |
| `rockwell_st` | **Logix-flavoured dialect with invented instructions** | 4 | `program.l5k` only | hand-written `reference.st` |
| `stress` | Self-authored, written by this project's AI tooling | 1 | `program.st` | the same `program.st` |
| `public_st` | Public programs, adapted. **`p03` and `p04` pass the translator, so they say nothing about model against baseline** | 4 | `program.st` | the same `program.st` |
| `ecc_persistent` | 4 programs from `corpus/`, accepted by the translator but in the wrong form | 4 | the unedited `corpus/*/program.st` | the same |

Each program directory holds its source and four stimuli, all from `corpus_hard/generate_stimuli.py`, seeded, using the classes of `corpus/generate_stimuli.py` and `corpus/generate_heldout.py`:

| File | Used for | Period | What makes it different |
|---|---|---|---|
| `stimulus.json` | Tuning. Repair feedback may use it | 10 or 100 ms | Seed 61499 |
| `heldout_stimulus.json` | The score, never shown | same | Seed 104729, jittered holds, closing and retune phases, a different start from scan 0, and directed phases at parameter values tuning never holds |
| `heldout_stimulus_2.json` | The score too, never shown. A run must pass both | 7 or 70 ms | Seed 104759, holds stretched to the same time, a different start, and parameters pinned for the whole file to values no other stimulus holds |
| `pairing_stimulus.json` | Only `scripts/check_pairing.py` | same as tuning | Seed 15485863 |

`control_flat.st` or `reference.st`, or `corpus_hard/ecc_persistent/*/control.fbt`, is a **solvability control**: a known-good solution, never shown to a model. A control that fails means a model failure there would say nothing, so `python3 -m st2fb.llm.hard_check` runs every control on real FORTE against matiec on all scored stimuli.

### Why held-out has two files

The contract keeps one `scan_ms` per stimulus file. The first review found that held-out added almost nothing: 3 mutants of 1713 were seen only on it, a migration that hard-coded the 10 ms period passed everything, and many numeric inputs never moved at all. Now:

- **The period changes.** A migration that writes `T#10ms` in place of `SCAN_DT` passes tuning and the first held-out file and fails the second. So does one that writes 10 for `TaskPeriodMs`, or `10.0` in the `r02` totaliser. `tests/test_hard_corpus.py` runs the first on real FORTE, and the others on matiec. 7 is on no grid of 10, so a preset multiple of 10 no longer lands on a scan.
- **Every numeric input moves, and tuning does not hold the values that test generalisation.** `s02.i_alarmDelay`, `s08.i_maxSpeed`, `r02.StartPct/StopPct`, `u01.BAND/SPAN/DISAGREE_DELAY` and `x01.LEVEL_STOP/LEVEL_1-3/RETRY_DELAY/STAGE_DELAY/ROTATE_TIME` have one value on tuning, and other values on held-out. `scripts/audit_stimuli.py` lists any numeric input constant across the scored stimuli, or with no value on held-out that tuning lacks, and a test runs it. It finds none. `s06` bit cases 384 and 512 are on held-out only, and they kill a read of bit 7 without its `MOD`.
- **No identical start.** Each held-out file differs from tuning from scan 0, so counting scans cannot stand in for behaviour. `hard_check` fails a program that shares more than one first scan with tuning.

### unsupported_st: valid ST outside the translator's scope

| Program | Out-of-scope constructs |
|---|---|
| `u01_sensor_voting` | user `FUNCTION`s, `RETURN`. Uses `REAL_TO_INT` |
| `u02_valve_manifold` | a user function block with state, instantiated three times |
| `u03_tank_strapping` | declared array type with initial values, `REPEAT`, `EXIT`, `RETURN`. Uses `REAL_TO_DINT` |
| `u04_alarm_ring` | declared structure, array of it, `EXIT`, `FOR ... BY -1` |
| `u05_pump_duty_records` | array of structures, `VAR CONSTANT`, `VAR_TEMP`, `EXIT` from two loops |
| `u06_cascade_nested` | two levels of nested user blocks, `RETURN` inside a nested block, `**`, `REAL_TO_INT` |

These lists live here and not in the sources, which reach the model.

### siemens_scl: TIA-style, never compiled, judged by matiec readings

**These SCL files were NOT compiled by TIA Portal, because none is available. They may not import. The oracle is a hand-written translation into plain ST, `reference.st`, so an error in the pairing would count against the model. Inspect any such failure instead of assuming the model is wrong.**

They were written in the TIA style from general knowledge: `#var`, `REGION`, `{ S7_Optimized_Access }`, `TON_TIME`, `IEC_TIMER`, `NORM_X`, `SCALE_X`, `T_ADD`, `ROUND`, `SQR`, `+=`, `CONTINUE`, `.%Xn` slices, `Array[..] of Struct`, `VAR CONSTANT`.

**Disputed readings are designed out where that was simple.** matiec's standard library is not Siemens's, and an independent review found that `s03` and `s08` scored differently under another plausible reading of `F_TRIG` (a first-scan pulse gave a phantom carton with all inputs low), `CTU_INT` (matiec stops at PV) and `SR` and `RS` (priority differs from LAD). So in both the vendor source and the reference:

- `s08`: the falling edges are `statXPrev AND NOT x`, on variables starting FALSE, so there is no first-scan pulse. The count is an IF with an explicit guard at the batch size. The reject count is an IF. The jam latch is an IF, with set first.
- `s03`: the fault latch is an IF, with the acknowledge first.
- `s01`, `s02`, `s03`, `s08`: each timer's PT comes from a variable that takes its input only while that timer is idle. So PT never moves while a timer runs, and "PT sampled on the edge", "PT live" and "raising PT after expiry" read the same. This is in the program's logic now, so a migration has to keep it, and directed phases change the inputs mid-timing to test that.

`scripts/check_vendor_readings.py` swaps in each other reading and runs every scored stimulus on real matiec. A test requires no difference. It checks one thing: the score does not depend on these readings. It does not show that the reading used is right.

| Program | Readings checked, each giving no difference | Readings that remain, and are only stated in the dialect file |
|---|---|---|
| `s01_conveyor_starter` | TON PT sampled, TON PT live after expiry, TOF PT sampled | R_TRIG, and the scan on which ET moves: matiec's TON bodies |
| `s02_analog_input` | TON PT sampled, TON PT live after expiry | **`NORM_X` and `SCALE_X` outside their range are the plain formula, as the dialect file says.** The stimuli go there (`i_raw` of 30000 and -100). A real CPU's treatment of out-of-range values was not checked |
| `s03_valve_monitor` | TON PT sampled, TON PT live after expiry | R_TRIG, TON bodies, RETURN holding the timers uncalled |
| `s04_batch_steps` | TON PT sampled, TON PT live after expiry, CTU past PV (PV 500 is never reached) | `CTU_INT` below PV, TON bodies |
| `s05_lead_lag_array` | none apply: no timer or counter | R_TRIG |
| `s06_status_word` | none apply | R_TRIG, and `.%Xn` as the arithmetic in the dialect file |
| `s07_heater_pi` | none apply | `ROUND` half to even, and `LIMIT`, `SQR`, `SQRT` on REAL |
| `s08_packaging_counter` | TON PT sampled, TON PT live after expiry, TP PT sampled | TP and TON bodies. `F_TRIG`, `CTU_INT` and `SR` no longer appear |

After this no Siemens program uses `SR`, `RS` or `F_TRIG`, so their parameter names (`S1`/`R`, `S`/`R1`) and the question of their priority no longer arise, and the dialect file no longer mentions them. `u01`, `u02` and `x01` still use `RS` and `SR` in plain ST, read as IEC and matiec do, which is what that set is judged on. `s04` keeps one `CTU_INT`, below PV.

| Program | Exercises |
|---|---|
| `s01_conveyor_starter` | R_TRIG, TON_TIME, TOF_TIME, `ET =>`, VAR_TEMP |
| `s02_analog_input` | NORM_X, SCALE_X, LIMIT with named arguments, IEC_TIMER, VAR CONSTANT |
| `s03_valve_monitor` | IEC_TIMER, T_ADD, RETURN, `+=` |
| `s04_batch_steps` | CASE with step numbers, TON_TIME with a shared changing preset, CTU_INT |
| `s05_lead_lag_array` | array of Struct, CONTINUE, EXIT, MAX with named arguments |
| `s06_status_word` | Word, `.%Xn` read and write, UINT_TO_WORD, hexadecimal literal |
| `s07_heater_pi` | RETURN, ROUND, SQR, SQRT, LIMIT, a first-run load |
| `s08_packaging_counter` | TP_TIME, TON_TIME, explicit edges and counts, SEL and MIN with named arguments |

The meaning the oracle gives each instruction is written in `st2fb/llm/prompt_files/dialect_siemens_scl_v1.md`, the same text the model reads. Vendor timers take matiec's semantics, not those of a real S7 CPU. Time conversions (`TIME_TO_DINT`) are avoided, since matiec counts seconds there and FORTE has no such function.

### rockwell_st: Logix-flavoured dialect with invented instructions

**These were NOT compiled or imported by Studio 5000, because none is available. The oracle is hand-written, so an error in the pairing would count against the model.** Instruction availability was not checked against Rockwell's manuals: in particular `RES` on an `FBD_TIMER` from structured text may not exist in real Logix. The file layout imitates L5K text from memory and is not a claim of L5K validity. So treat `TONR`, `CTUD`, `OSRI` and `RES` here as instructions of a dialect defined by `st2fb/llm/prompt_files/dialect_rockwell_logix_v1.md`, and not as Logix.

Real Logix timers read the controller's clock. Here, an AOI has a DINT input `TaskPeriodMs`, and `TONR` adds it to `.ACC`. That is a deliberate deviation, for one reason: `.ACC` and `.PRE` are DINT milliseconds, and the FORTE target has no conversion between TIME and a number. Each stimulus file sets it to that file's scan period on every scan, and a test pins that.

**All four programs depend on the dialect file's reading that the first enabled `TONR` call leaves `.ACC` at 0.** With a timer that counts on that scan instead, `scripts/check_vendor_readings.py` finds differences on every scored stimulus of `r01`, `r02`, `r03` and `r04`. Removing this was not simple, since it is the meaning of the invented instruction, so it is stated here and in the dialect file. A pass means the FB follows the dialect file.

| Program | Exercises |
|---|---|
| `r01_motor_aoi` | `.TimerEnable`, `.PRE`, `.ACC`, `.DN`, `.EN`, `.TT`, OSRI, RES |
| `r02_fill_retry_aoi` | two timers, CTUD that does not stop at PRE, RES on a timer and a counter, REAL totaliser |
| `r03_sequence_aoi` | CASE, RES at each step change, `[:=`, a shared preset |
| `r04_alarm_word_aoi` | bit access `x.n` for read and write, three delayed alarms, first-out |

### stress

`x01_pump_station` is the most demanding single program: three pumps, each a state machine with proving, retries and a latched lockout; duty rotation on least run ticks; staged start with a delay; interlocks that stop without counting as failures; maintenance; a station alarm. It was written by this project's AI tooling, and its `README.md` says so, rather than its source, which reaches the model. Its `set.json` records `max_tokens` 21333, which a run uses unless `--max-tokens` is given, since the estimate of its first reply is near the default limit.

The review found its random phase kept the station idle: interlocks toggled at random were low about half the time, and a toggled reset cleared every retry count. So the random phase now runs interlocks and trips as short events. Directed phases were added, in tuning and both held-out files: lockout then an interlock drop, so `IF NOT PERMIT AND STATE <> 4` and its `4 -> 3` and `4 -> 5` mutants are killed; holds of 24 scans on each start level, so `>=` to `>` is killed; a three-retry lockout. `python3 scripts/x01_state_reach.py`, on real matiec, on a copy with STATE exposed (and every original output checked unchanged):

```
stimulus.json: 1982 scans. Highest retry count 3. Stages [0, 1, 2, 3]. Duty [0, 1, 2, 3].
  pump 1: idle 1075, proving 76, running 517, waiting to retry 24, locked out 290
  pump 2: idle 1048, proving 108, running 434, waiting to retry 44, locked out 348
  pump 3: idle 1073, proving 127, running 339, waiting to retry 48, locked out 395
heldout_stimulus.json: 3131 scans. Highest retry count 4. Stages [0, 1, 2, 3]. Duty [0, 1, 2, 3].
  pump 1: idle 1830, proving 173, running 501, waiting to retry 74, locked out 553
  pump 2: idle 2083, proving 128, running 570, waiting to retry 47, locked out 303
  pump 3: idle 1926, proving 179, running 511, waiting to retry 69, locked out 446
heldout_stimulus_2.json: 3506 scans. Highest retry count 4. Stages [0, 1, 2, 3]. Duty [0, 1, 2, 3].
  pump 1: idle 1011, proving 229, running 773, waiting to retry 155, locked out 1338
  pump 2: idle 1252, proving 204, running 960, waiting to retry 134, locked out 956
  pump 3: idle 1152, proving 208, running 766, waiting to retry 133, locked out 1247
Every pump reaches every state on every stimulus, and a retry count passes 2 on every stimulus.
```

### Public programs (`public_st`)

Found by a bounded search of about 30 minutes. It is not exhaustive: GitHub code search needs authentication, and no token was available.

| Program | Project | Commit | Licence | Translator |
|---|---|---|---|---|
| `p01_bistable_device` | https://github.com/tkucic/plc_hello_mixing_tank | `17e0213b1c7c46fd44ff7d9a52a6bb9e500d65de` | MIT, Copyright (c) 2021 Toni Kucic | rejected: USINT state variable |
| `p02_pi_controller` | https://github.com/Intecre/twincat-utils | `cd7a087d885d2d415e5eeb497bfe3237843f3fed` | MIT, Copyright (c) 2022 Intecre Ltd | rejected: nested blocks, RETURN |
| `p03_alpha_beta_filter` | https://github.com/Intecre/twincat-utils | `cd7a087d885d2d415e5eeb497bfe3237843f3fed` | MIT, Copyright (c) 2022 Intecre Ltd | **accepted, passed** |
| `p04_debounce_bool` | https://github.com/anjlab/codebox | `baec19e84109f402a5e7e7a2b4cdd752e82298a5` | Apache-2.0, Copyright 2025 AnjLab | **accepted, passed** |

Each directory keeps the upstream `LICENSE` and a `NOTICE.md` with the file path and every change, compared with the upstream text on 2026-11-07. **`p02` and `p03` are not the upstream programs:** `LREAL` became `REAL`, so all their numbers are single precision, and in `p02` `T_Task` was replaced by a new input, and the integer literals in REAL context became REAL. `p01` and `p04` are the same text after normalising, except that `p04` drops two input initial values, which the harness overrides. `p03` and `p04` pass the translator, so they say nothing about model against baseline. `p01` falls to one front-end rule, USINT to UINT.

Licence coverage rests on the root licence file with no conflicting header in the file taken. Nobody checked whether the authors held the right to license this code, or whether it was machine-written. Rejected: GPL or LGPL projects (blark, Tc3_UnitTest, OpenSML, struckig, iec-checker, Beremiz, matiec), OSCAT-derived libraries, custom or placeholder licences (controltheplant/PID-controller, PLC_Tank_Level_PID), and projects that are not plain text or need a vendor framework. `nikspolaroid/codesys-vfd-pump-station` and `1337leets/PMDC-Motor-PID-Control-Modbus-HMI-OpenPLC` qualified on licence, but are days old with unknown provenance, so they were left out.

## Reference runner changes

`st2fb/reference_run.py` changed in two ways, both additive:

- `iec_std_lib.h` declares `iec_lib_fmod`, `iec_lib_pow`, `iec_lib_sqrt` and others and leaves them to the platform, so a program using REAL_TO_INT, REAL_TO_DINT, `**` or a math function failed to link. The driver now defines them as plain calls to the C library. matiec's own library code still does the rounding, half to even. FORTE gives the same on every value tried.
- A file with helper blocks marks the block under test with the comment `(* st2fb:dut *)`. Without a mark a file must still hold exactly one FUNCTION_BLOCK. The interface is read only from that block's text, so a helper's VAR_INPUT no longer leaks into it.

Both leave `corpus/` as it was: `tests/test_validation_reference.py` still passes, and a test confirms that the mutant lists of all 21 programs are unchanged.

## ecc_persistent: a strict metric

`restructured` counts states with actions. So a hub that returns to START on every scan and then dispatches on a variable counts, though the position lives in the variable and the ECC holds nothing between scans.

`st2fb/llm/ecc_metric.py` defines it, and its docstring is the full definition. The verdict is `persistent`, `not_persistent`, `needs_reading` or `unreadable`. Every variable is enumerated, a counter or data, whatever its type, and copies are followed back to a root. In short:

| Clause | Requires | Example that fails |
|---|---|---|
| C1 | at least two control states, each holding across scans, one reachable from another. A one-way chain qualifies | the translator's START -> RUN -> START, or a state left for good on the first REQ |
| C2 | no state on every scan path of every control state | every REQ going through one `COMMON` state |
| C3 | no carried-over enumerated value, or a copy of it, compared with two or more values by guards | `REQ[SEQ = 0]`, `REQ[SEQ = K1]`, `[COPY = 1]`, a REAL or a one-hot boolean copied from the position |
| C4 | no such value selecting branches in algorithms run from two or more control states | a shared `CASE SEQ OF`, or `K := SEQ; CASE K OF` |
| C5 | control states do not all run the same algorithms | two states that only toggle |

A static check cannot always tell, so where it cannot it returns `needs_reading`, with reasons, rather than guess: a counter dispatched from two control states (a retry count, or a step number?), carried-over booleans that may be a one-hot position, or guards that follow a shared and only sometimes-assigning algorithm. A report counts these apart, and a person reads them.

Exit guards are allowed: a guard on a variable that this scan's algorithm has already assigned from something other than a position is an exit test. A timer's state variable is left out only if its statements really are a lowered TON, TOF or TP body and no guard reads it. A name is not enough.

| Review fixture | Before | After | Why |
|---|---|---|---|
| `fa1_named_constants` | accepted | not_persistent, C3 | a variable nothing assigns counts as its value |
| `fa2_real_position` | accepted | not_persistent, C3 | all types alike, and `POS := INT_TO_REAL(SEQ)` is a copy |
| `fa3_timer_name_exempt` | accepted | not_persistent, C3 | the exemption needs a real timer body |
| `fa4_bool_one_hot` | accepted | not_persistent, C3 | booleans copied from one root count as that root |
| `fa5_arithmetic_guard` | accepted | not_persistent, C3 | `SEQ + 0 = 1` reads SEQ |
| `fa6_case_on_copy` | accepted | not_persistent, C4 | `K := SEQ` carries the position, so assigning K first exempts nothing |
| `fa7_guard_on_copy` | accepted | not_persistent, C3 | the same for a guard |
| `fr1_linear_no_return` | rejected, C1 | persistent, 3 control states | a one-way chain that holds in each position qualifies |
| `fr2_retry_counter_guards` | rejected, C3 | persistent, 3 control states | a counter compared with two values from one state is not a position |
| `fr3_hysteresis_integer` | rejected, C3 | persistent, 2 control states | it is data, computed from an input |
| `fr4_shared_mode_branch` | rejected, C4 | persistent, 2 control states | it is data, a setting taken from an input |

All are in `tests/fixtures/ecc/`, and each `fr` machine equals matiec on real FORTE, which a test runs. `tests/test_ecc_metric.py` replaced one positive fixture: `pos_shared_logic_timer_state` used a two-line variable that only happened to be named `X_STATE`, which is fa3 itself, so it now holds a real TON body. C4 counts tests and not literals, so a range test `IF STATE_NO >= 2 AND STATE_NO <= 4`, which the known-good supervisor control uses to derive an output from a state number it has just assigned, stays one branch. Two tests make it dispatch.

**The 168 candidates kept from the first benchmark rescored with this version: 163 `not_persistent`, 5 `unreadable`, 0 `needs_reading`, 0 `persistent`. The 5 unreadable are Sonnet candidates for `18_pump_station_rotation` with `<InternalVars>` outside `<BasicFB>`, which `fbt.py` now rejects by name. Before that parser change they scored `not_persistent`, so the outcome is the same: none is persistent. 22 of them count as `restructured`.** A test pins this, read-only.

It is static, and it says nothing about behaviour. A determined author could satisfy it with a meaningless ECC, for example with a separate conditional assignment in front of each state's guards, or by laundering a position through an input. Read the candidates too.

Behavioural equality stays the pass condition. A correct wrapper under `--form ecc_persistent` passes, with `Persistent: no`, and gets no repair attempt for its form. A test pins that.

`--form ecc_persistent` adds `form_ecc_persistent_v1.md` and a worked example to the system prompt, which override the Structure section and the hub example. With no `--programs` it runs four programs, none edited: `13_case_sequencer`, `14_batch_filling`, `20_pump_station_supervisor`, and `06_star_delta`, which has no CASE, so the states have to be found in its timer chain. `18_pump_station_rotation` has a CASE too, but it is a loop over pumps and not a state machine.

`corpus_hard/ecc_persistent/*/control.fbt`, from `scripts/build_ecc_controls.py`, shows that the form is reachable: all four meet the metric and equal matiec on tuning and held-out on real FORTE.

## Running it

    python3 -m st2fb.llm.hard_check                # no model: both tiers, oracle, every control. Records the manifest on a pass
    python3 scripts/check_pairing.py               # no model: the two pairing checks
    python3 scripts/check_vendor_readings.py       # no model: does a score depend on a disputed reading?
    python3 scripts/check_plausible_faults.py      # no model: what do the stimuli see of plausible migration faults?
    python3 scripts/audit_stimuli.py               # no model: any numeric input not exercised?
    python3 scripts/x01_state_reach.py             # no model: how deep the stress stimuli go
    python3 -m st2fb.mutate campaign --corpus corpus_hard --uncapped --jobs 8 --save-json corpus_hard/mutation_results.json \
        --notes corpus_hard/mutation_survivor_notes.json --report docs/HARD_MUTATION_RESULTS.md
    python3 scripts/fbt_mutation_campaign.py --corpus corpus_hard --count 5 --jobs 6 --notes corpus_hard/fbt_mutation_survivor_notes.json \
        --report docs/HARD_FBT_MUTATION_RESULTS.md --save-json corpus_hard/fbt_mutation_results.json
    python3 -m st2fb.llm.benchmark --dry-run --no-fallbacks --corpus-dir corpus_hard/siemens_scl --modes llm_repair --model claude-sonnet-5-5:1
    python3 -m st2fb.llm.benchmark --dry-run --no-fallbacks --form ecc_persistent --modes llm_repair --model claude-opus-5-5:1
    python3 scripts/estimate_hard_cost.py          # an estimate, from the first benchmark's tokens

- `--corpus-dir` takes one or more sets. `--form` can be combined with it. Without `--live`, the fake client runs and writes to `build/llm_hard/fake/`.
- **A real run needs a recorded pass.** A benchmark on this corpus, fake or live but not `--dry-run`, refuses to start unless `hard_check` passed on exactly these files. `st2fb/llm/manifest.py` hashes every program file, the set settings, the prompt files and the `ecc_persistent` programs and controls, and `hard_check` writes that hash to `build/llm_hard/hard_check.json` only if the whole corpus passed. A live client is refused in `run_benchmark` itself, however it was started.
- **Reports** go to `build/llm_hard/reports/<set>/`, and the **ledger and cache** to `build/llm_hard/`, so `--budget-usd` is one cumulative cap across all hard runs, as `docs/LLM.md` describes for the first benchmark. It starts from zero: its ledger is separate from `build/llm/ledger.jsonl`.
- `run_benchmark` refuses any path in or under `results/benchmark_2026-11-06`.
- The report has a Baseline tiers section, with `Translator` and `Frontend+translator` columns per program, and `Passed where translator rejected`, `Passed where frontend+translator did not pass`, `Passed and persistent` and `Passed, needs reading` in the aggregate. The wording above is in every report, with the true count.
- **Unchanged:** budget code and its checks. With neither option given, the prompts, cache keys and report format are those of the first benchmark. Tests confirm that its report renders byte for byte from its JSON, the sha256 of each old prompt file, and that all 84 first-attempt cache keys of the published run still find their responses in `build/llm/cache` (the published run used `--no-fallbacks`, which is part of the key).

## Prompts

New files only, each versioned: `addendum_hard_v1.md`, `dialect_iec_st_extended_v1.md`, `dialect_siemens_scl_v1.md`, `dialect_rockwell_logix_v1.md`, `generate_dialect_v1.md`, `form_ecc_persistent_v1.md`, `example_persistent_v1.fbt`. A hard prompt is the old system prompt followed by these. A test checks that none of them names a program or any program's interface variable, except `TaskPeriodMs`, which is a convention of the dialect. No model has read them, so they could still be edited: the Siemens file lost `F_TRIG`, `SR` and `RS`.

`tests/test_hard_leakage.py` builds every prompt of every program offline with sockets blocked, and checks that none holds a held-out row, a line of a reference, control, README or NOTICE, a path, or a hint. It also drives wrong, uncompilable and invalid replies through real FORTE with the fake client, and checks the same of each repair request. The source comments that reached the model were removed: "Out of scope for the translator: ...", "Written by this project's AI tooling", "RETURN ... leaves only that block", and the half-to-even note in `s07`. Attribution stays in `README.md`, `NOTICE.md` and this file, which a model does not see. The licence notice at the top of each public program stays.

The dialect file is what the oracle takes the dialect to mean, and it is the same for all programs of a dialect. Without it, a model could not know what it is judged against.

## Mutation check

`python3 -m st2fb.mutate campaign --uncapped`, matiec against mutated matiec, **every mutant of every program on every scored stimulus, with no cap and no sampling**. For a paired program it mutates `reference.st`, so it asks whether the stimuli would notice a slip in the hand translation of about this size. It does not show that a pairing is correct: that is what the next section is for. Every survivor with its analysis is in `docs/HARD_MUTATION_RESULTS.md`.

**1650 of 1756 counted mutants detected (94.0%)**, 106 survived all stimuli, 152 rejected by the compiler and not counted. Tuning alone sees 1634, held-out alone sees 1650. **Only tuning sees 0, and only held-out sees 16.**

The earlier number, 95.4% of 998, was capped at 60 per program and on tuning only. The review's uncapped run on that corpus had 1713 counted, tuning 1584, held-out 1579, neither 126, only tuning 8, only held-out 3. So the corrected before-and-after is 92.6% (1587 of 1713, on two stimuli) against 94.0% (three stimuli, on a corpus with slightly different programs). The mutant lists differ, since the references changed.

Each of the 106 survivors was read one by one: 92 equivalent, 2 equivalent on any realistic stimulus, 4 gap, listed, 8 meaningless. **That is reasoned from reading the program and the mutant, not proved, and no equivalence checker was run.**

### What each stimulus sees

| Set | Program | Counted | Tuning detected | Held-out detected | Tuning only | Held-out only | Survived all |
|---|---|--:|--:|--:|--:|--:|--:|
| public_st | p01_bistable_device | 30 | 30 | 30 | 0 | 0 | 0 |
| public_st | p02_pi_controller | 46 | 42 | 42 | 0 | 0 | 4 |
| public_st | p03_alpha_beta_filter | 22 | 21 | 21 | 0 | 0 | 1 |
| public_st | p04_debounce_bool | 11 | 11 | 11 | 0 | 0 | 0 |
| rockwell_st | r01_motor_aoi | 72 | 62 | 64 | 0 | 2 | 8 |
| rockwell_st | r02_fill_retry_aoi | 107 | 82 | 85 | 0 | 3 | 22 |
| rockwell_st | r03_sequence_aoi | 162 | 121 | 122 | 0 | 1 | 40 |
| rockwell_st | r04_alarm_word_aoi | 161 | 155 | 158 | 0 | 3 | 3 |
| siemens_scl | s01_conveyor_starter | 26 | 26 | 26 | 0 | 0 | 0 |
| siemens_scl | s02_analog_input | 42 | 36 | 40 | 0 | 4 | 2 |
| siemens_scl | s03_valve_monitor | 26 | 25 | 26 | 0 | 1 | 0 |
| siemens_scl | s04_batch_steps | 97 | 93 | 93 | 0 | 0 | 4 |
| siemens_scl | s05_lead_lag_array | 97 | 94 | 94 | 0 | 0 | 3 |
| siemens_scl | s06_status_word | 93 | 92 | 93 | 0 | 1 | 0 |
| siemens_scl | s07_heater_pi | 41 | 41 | 41 | 0 | 0 | 0 |
| siemens_scl | s08_packaging_counter | 42 | 41 | 42 | 0 | 1 | 0 |
| stress | x01_pump_station | 255 | 249 | 249 | 0 | 0 | 6 |
| unsupported_st | u01_sensor_voting | 46 | 46 | 46 | 0 | 0 | 0 |
| unsupported_st | u02_valve_manifold | 39 | 39 | 39 | 0 | 0 | 0 |
| unsupported_st | u03_tank_strapping | 42 | 42 | 42 | 0 | 0 | 0 |
| unsupported_st | u04_alarm_ring | 125 | 119 | 119 | 0 | 0 | 6 |
| unsupported_st | u05_pump_duty_records | 89 | 84 | 84 | 0 | 0 | 5 |
| unsupported_st | u06_cascade_nested | 85 | 83 | 83 | 0 | 0 | 2 |
| **all** | | **1756** | **1634** | **1650** | **0** | **16** | **106** |

"Only held-out" is the number that says held-out adds testing power. It counts token-level slips only. `scripts/check_plausible_faults.py` tries plausible migration mistakes as well, and most of the hard-coded or frozen ones are seen by held-out alone, as designed: `TaskPeriodMs` as 10 in each Logix program, the frozen alarm delay in `s02`, max speed in `s08`, start and stop levels in `r02`, and span in `u01`.

### What some mutants really exercise

- `r03_sequence_aoi`: every statement of the RES on abort and of the RES at the end of a cycle can be removed with no visible change. Each sets `StepNo` to 0 on the same scan, so the disabled timer call later in the scan does the same work. They exercise nothing, so a migration may drop them and be correct.
- `r02_fill_retry_aoi`: `Retries_PREV` cannot show. The counter's input is `OpenTimer.DN`, which is high for one scan at a time, and the dialect's rule that RES keeps a counter's previous input cannot show either, since `RES(OpenTimer)` clears that input on the same scan. So CTUD's edge memory is present and not tested. No other program uses CTUD.

### FORTE side

`scripts/fbt_mutation_campaign.py --corpus corpus_hard --count 5`: about 5 mutants per program, in the `.fbt` of `frontend+translator`, or of `control_flat.st` where the front-end does not get through, through the exporter, g++ and real FORTE, against unmutated matiec. **94 of 114 counted mutants detected on tuning, 20 survived tuning, 1 failed to compile and are not counted.** Of the 20 survivors, 1 were caught on a held-out file. Details in `docs/HARD_FBT_MUTATION_RESULTS.md`. It is a small sample, and it says that the FORTE path can see a broken FB, and nothing about a model.

## Checks of the pairing, and what they do not check

Neither TIA Portal nor Studio 5000 is available, so these are the best checks here, and they are weaker than compiling the vendor source. **Both are independent of the hand translation. Neither is independent of this project's reading of the vendor language.**

**Check A, all 12 paired programs.** `scripts/check_pairing.py` has `st2fb/vendor_frontend.py` rewrite the vendor file by rule, and runs matiec on that and on `reference.st` on every stimulus, `pairing_stimulus.json` included. All 12 are equal on all four stimuli. It shares matiec with the oracle, and its rules come from the same dialect files as the reference.

**Check B, five programs.** A Python model of `s01`, `s03`, `s06`, `r01` and `r02`, written from the vendor file statement by statement, against matiec on `reference.st`, on `pairing_stimulus.json`. All five are equal. **This is independent of matiec's execution and not independent of the reading of the vendor language:** the same author wrote both, and the models read each vendor timer as the dialect prompt does. A negative control in `tests/test_hard_corpus.py` changes one `AND NOT` to `OR NOT` in each reference and confirms the model then disagrees.

A shared misreading of a vendor language would show in neither. These check the logic of the translation, and not whether that reading matches real hardware. The `r02` logic fault found earlier was in the program itself, on both sides of the pair, and only mutation testing showed it.

## Results of the checks, per program

| Set | Program | Translator | Frontend+translator | Translator's reason | Control (tuning/held-out/held-out 2) | Scan ms | Scans | Output changes | Mutants detected |
|---|---|---|---|---|---|---|---|---|--:|
| unsupported_st | `u01_sensor_voting` | rejected | rejected | line 2:1: expected FUNCTION_BLOCK, found 'FUNCTION' | equal/equal/equal | 10/10/7 | 403/988/920 | 311/494/345 | 46 of 46 |
| unsupported_st | `u02_valve_manifold` | rejected | rejected | line 27:1: unexpected 'FUNCTION_BLOCK' | equal/equal/equal | 10/10/7 | 426/919/814 | 243/360/383 | 39 of 39 |
| unsupported_st | `u03_tank_strapping` | rejected | rejected | line 3:22: unexpected character '[' | equal/equal/equal | 100/100/70 | 414/744/764 | 630/553/509 | 42 of 42 |
| unsupported_st | `u04_alarm_ring` | rejected | rejected | line 24:15: unexpected character '[' | equal/equal/equal | 10/10/7 | 429/924/988 | 419/431/452 | 119 of 125 |
| unsupported_st | `u05_pump_duty_records` | rejected | rejected | line 28:15: unexpected character '[' | equal/equal/equal | 100/100/70 | 744/1194/1269 | 644/920/1181 | 84 of 89 |
| unsupported_st | `u06_cascade_nested` | rejected | rejected | line 19:1: unexpected 'FUNCTION_BLOCK' | equal/equal/equal | 100/100/70 | 456/788/847 | 385/720/828 | 83 of 85 |
| siemens_scl | `s01_conveyor_starter` | rejected | passed | line 1:16: unexpected character '"' | equal/equal/equal | 10/10/7 | 528/1076/917 | 150/188/173 | 26 of 26 |
| siemens_scl | `s02_analog_input` | rejected | passed | line 1:16: unexpected character '"' | equal/equal/equal | 10/10/7 | 370/1401/1519 | 202/379/307 | 40 of 42 |
| siemens_scl | `s03_valve_monitor` | rejected | passed | line 1:16: unexpected character '"' | equal/equal/equal | 10/10/7 | 459/962/842 | 256/356/431 | 26 of 26 |
| siemens_scl | `s04_batch_steps` | rejected | passed | line 1:16: unexpected character '"' | equal/equal/equal | 10/10/7 | 711/1300/1153 | 284/531/499 | 93 of 97 |
| siemens_scl | `s05_lead_lag_array` | rejected | rejected | line 1:16: unexpected character '"' | equal/equal/equal | 100/100/70 | 362/699/722 | 209/405/372 | 94 of 97 |
| siemens_scl | `s06_status_word` | rejected | passed | line 1:16: unexpected character '"' | equal/equal/equal | 10/10/7 | 325/1290/1340 | 155/233/265 | 93 of 93 |
| siemens_scl | `s07_heater_pi` | rejected | passed | line 1:16: unexpected character '"' | equal/equal/equal | 100/100/70 | 374/715/719 | 524/968/696 | 41 of 41 |
| siemens_scl | `s08_packaging_counter` | rejected | passed | line 1:16: unexpected character '"' | equal/equal/equal | 10/10/7 | 543/1137/1244 | 223/348/375 | 42 of 42 |
| rockwell_st | `r01_motor_aoi` | rejected | passed | line 1:64: unexpected character '"' | equal/equal/equal | 10/10/7 | 644/1163/1066 | 184/289/237 | 64 of 72 |
| rockwell_st | `r02_fill_retry_aoi` | rejected | passed | line 1:61: unexpected character '"' | equal/equal/equal | 10/10/7 | 708/1263/1341 | 185/523/352 | 85 of 107 |
| rockwell_st | `r03_sequence_aoi` | rejected | passed | line 1:63: unexpected character '"' | equal/equal/equal | 10/10/7 | 691/1255/1142 | 265/509/493 | 122 of 162 |
| rockwell_st | `r04_alarm_word_aoi` | rejected | passed | line 1:61: unexpected character '"' | equal/equal/equal | 10/10/7 | 493/1006/1064 | 312/456/440 | 158 of 161 |
| stress | `x01_pump_station` | rejected | rejected | line 124:15: unexpected character '[' | equal/equal/equal | 10/10/7 | 1982/3131/3506 | 1837/2375/3249 | 249 of 255 |
| public_st | `p01_bistable_device` | rejected | passed | vState: type USINT is outside the v1 subset | equal/equal/equal | 10/10/7 | 459/979/832 | 38/64/40 | 30 of 30 |
| public_st | `p02_pi_controller` | rejected | rejected | line 15:1: unexpected 'FUNCTION_BLOCK' | equal/equal/equal | 100/100/70 | 447/780/840 | 306/451/346 | 42 of 46 |
| public_st | `p03_alpha_beta_filter` | passed | passed |  | equal/equal/equal | 100/100/70 | 276/595/616 | 271/533/585 | 21 of 22 |
| public_st | `p04_debounce_bool` | passed | passed |  | equal/equal/equal | 10/10/7 | 417/904/765 | 31/47/21 | 11 of 11 |

| ecc_persistent | Metric on control | Control states | Control |
|---|---|--:|---|
| `06_star_delta` | persistent | 4 | equal / equal |
| `13_case_sequencer` | persistent | 9 | equal / equal |
| `14_batch_filling` | persistent | 5 | equal / equal |
| `20_pump_station_supervisor` | persistent | 6 | equal / equal |

`Control` is the solvability control on real FORTE against matiec. `Frontend+translator` is the same, for what the front-end produces: `rejected` there means the translator still rejects its output. `Mutants` is uncapped, on all stimuli. No output is static on any scored stimulus of any program.

## Cost

Worst cases from `--dry-run --no-fallbacks --modes llm_repair`, each row one repeat of each model. They are the limit that the budget code enforces. The estimates are from `scripts/estimate_hard_cost.py`, using the tokens the first benchmark measured, and are **not a measurement of these programs**.

| Set | Model | Requests at most | Worst case USD | Estimate, low USD | Estimate, high USD |
|---|---|--:|--:|--:|--:|
| unsupported_st | claude-sonnet-5-5 | 18 | 4.10 | 0.23 | 1.42 |
| unsupported_st | claude-opus-5-5 | 18 | 8.21 | 0.46 | 2.88 |
| siemens_scl | claude-sonnet-5-5 | 24 | 5.63 | 0.32 | 1.96 |
| siemens_scl | claude-opus-5-5 | 24 | 11.25 | 0.64 | 3.98 |
| rockwell_st | claude-sonnet-5-5 | 12 | 2.81 | 0.16 | 0.94 |
| rockwell_st | claude-opus-5-5 | 12 | 5.63 | 0.32 | 1.91 |
| public_st | claude-sonnet-5-5 | 12 | 2.73 | 0.13 | 0.77 |
| public_st | claude-opus-5-5 | 12 | 5.46 | 0.26 | 1.55 |
| stress | claude-sonnet-5-5 | 3 | 0.90 | 0.15 | 0.77 |
| stress | claude-opus-5-5 | 3 | 1.80 | 0.30 | 1.53 |
| ecc_persistent | claude-sonnet-5-5 | 12 | 2.81 | 0.30 | 1.82 |
| ecc_persistent | claude-opus-5-5 | 12 | 5.62 | 0.60 | 3.68 |
| **all six** | claude-sonnet-5-5 | 81 | 18.98 | 1.29 | 7.68 |
| **all six** | claude-opus-5-5 | 81 | 37.97 | 2.58 | 15.53 |

`x01` uses its recorded `max_tokens` of 21333. With fallbacks on, each worst case about doubles, and the dry-run footer says which applies.

Check the prices against the current list first: they were cached on 2026-10-06. The estimate's low column assumes every program passes first time at the first benchmark's output per byte. Its high column assumes three attempts each at twice that output. Harder programs may need more thinking than the first benchmark's, so the true figure could be outside this range, though not outside the worst case.

## Limits

- Writing all the Siemens and Rockwell programs and their references took one sitting, by one author, so a shared misunderstanding of a vendor language is the likeliest error. It would show up as a model failing against a wrong oracle, which is why a failure there has to be inspected.
- Held-out stimuli come from the same scenario as tuning, with new values, a new start, a new period and directed phases. They test different timing and combinations, not a different idea of what the program is for.
- Vendor semantics are this project's reading. Nothing here shows that a passing migration matches a real S7 or Logix controller. It shows that it matches matiec on the hand translation.
- **A correct FB can fail on rounding where a value cancels near zero.** `compare` has a relative tolerance of 1e-5 and no absolute floor. This happened once. Under the first seed of `u06`'s second held-out file, one scan's `VALVE_PCT` cancelled to about 0.09, and matiec's `** 0.5` and FORTE's are a unit in the last place apart, which cancellation lifted to a relative difference of 2.8e-5. So the solvability control failed, and no correct FB could have passed. That file now has another seed, which is recorded in the generator, and `hard_check` would catch the same thing elsewhere for the control. It would not catch it for a rewrite the control does not make, so inspect a failure of one or two scans on a small REAL before calling it wrong. Reorderings tried in `scripts/check_plausible_faults.py` show no difference now, including `SQRT` for `** 0.5`.
- Each period adds a second stimulus only. A mutant that needs some other grid can still survive, such as two in `r03`, and they are listed.
