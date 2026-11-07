# Survivors of the mutation check on the model's own files, and a reading check of the candidates

Date: 2026-11-07. Repo state: commit `334d3dd`, clean tree. No Anthropic API call was made. No corpus file or code was changed.
Everything below was run or read for this file, except where it says otherwise.

## Result

The check mutated Sonnet 5.5's final `.fbt` for all 27 hard-run programs and ran each mutant on one stimulus, `heldout_stimulus.json`.

| Sample | Programs | Mutants | Killed | Survived | Source |
|---|--:|--:|--:|--:|---|
| Second, `--count 5 --seed 61499` | 20 (16 hard + 4 ECC form) | 100 | 84 | 16 | `independent_check_output.txt` |
| First, `--count 6 --seed 61499` | 7 (`u01`..`u06`, `x01`) | 42 | 36 | 6 | scratch `hardv/mut/`, recounted from its reports. Not kept in the repo |
| **Total** | **27** | **142** | **120** | **22** | |

Verdict on the 22 survivors, after running each on every other stimulus and reading its code:

| Verdict | Second sample (16) | First sample (6) | Total |
|---|--:|--:|--:|
| Caught by another scored stimulus | 0 | 0 | **0** |
| Equivalent, reasoned and not proved | 14 | 6 | **20** |
| Real test gap, shown by a stimulus that kills the mutant | 2 | 0 | **2** |

- No survivor was caught by `heldout_stimulus_2.json` or `stimulus.json`, so running the mutants on every scored stimulus would not have raised the 120.
- The two gaps are narrow: a zero preset on `p01`, and a negative `deltaInSecond` on `p03`, which the source's own comment forbids.
- One of the 20, `p03` mutant_000, is equivalent only on FORTE, because FORTE's division returns 0 on a zero divisor. See "Side findings".
- **"Equivalent" here is an argument from reading. No equivalence checker ran.** Do not quote 120 of 122 or 98.4% as a measured number.
- A survivor analysis says what these mutants show about the stimuli. It says nothing about mutants not sampled, about real S7 or Logix behaviour, or about any real plant.

## Method

For each survivor, using the repo's own tools and real Docker images (`st2fb-forte:efcd63c`, `st2fb-matiec:3a41303`):

```
python3 -m st2fb.reference_run --st <reference or program> --stimulus <S> --out m.json
python3 -m st2fb.forte_run --fbt <mutant> --stimulus <S> --out f.json
python3 -m st2fb.compare m.json f.json --out r.json
```

- `S` was `heldout_stimulus.json` again, then `heldout_stimulus_2.json`, `stimulus.json`, and the 1200-scan random stimulus from the independent check, which is not scored.
- The four `ecc_*` programs come from `corpus/`, which has no `heldout_stimulus_2.json`, so they have one scored stimulus fewer.
- 86 runs, all `equal`, 0 divergences. These mutants were already built, and `build/forte_cache` did not grow from these runs.
- I then read the changed line in context and classified it.
- A verdict of "gap" needs a kill. I wrote a small stimulus to kill it, and `compare` had to report a difference.
- As extra evidence for the "equivalent" verdicts I ran an unscored fuzz stimulus, described below. It cannot prove equivalence. It could only have refuted a verdict, and the only mutant it separated is one already classed as a gap.

## Every survivor

Scan counts are for held-out / held-out 2 / tuning / random. Every cell compared equal.

### Second sample, 16 mutants

| Program, mutant | Scans | Change, as read in the `.fbt` | Verdict | Why |
|---|---|---|---|---|
| `ecc_06` 004 | 1427 / n/a / 767 / 1200 | removed `GAP_TIMER_STATE := 2` | Equivalent | `GAP_TIMER_PT` is the literal `T#50ms` and `ST2FB_NOW` only grows, so the timer re-enters the same branch each scan and sets the same `Q`. `ET` of this timer is not an output |
| `ecc_14` 003 | 1506 / n/a / 981 / 1200 | `+` to `-` in `tmr_a`'s expiry test | Equivalent | `tmr_a` starts with `SETTLE_TIMER_IN := FALSE`, so `IF NOT IN` always wins and this branch is dead code. It runs only in states where the source's `IN` is false |
| `p01` 000 | 979 / 832 / 459 / 1200 | `<=` to `<` in the state-1 entry reset | Equivalent | Same dead branch: `IN` was set to FALSE two lines before |
| `p01` 002 | same | negated the start condition in the state-1 entry reset | **Real gap** | Takes the "start" path on entry instead of the reset path. Same output unless `cfgDeactTime = 0`. Killed by a zero-preset stimulus (below) |
| `p01` 003 | same | `AND` to `OR` in the same condition | Equivalent | With `IN` false it reduces to `STATE = 0`. This block is entered only after `Q` fired in state 0, so `STATE` is 2 there |
| `p01` 004 | same | removed `TransitionDelay_ET := T#0s` | Equivalent | `TransitionDelay_ET`: 12 writes, 0 reads, not an output |
| `p02` 000 | 780 / 840 / 447 / 1200 | `i_integral < i_Min` to `<=` | Equivalent | When equal, the branch assigns the value it already has |
| `p03` 000 | 595 / 616 / 276 / 1200 | `deltaInSecond > 0.0` to `>=` | Equivalent **on FORTE only** | Each stimulus has one scan with delta 0 and beta not 0, so the mutant really divides by 0. FORTE's `DivOperation` returns 0 and logs an error, which is what the else branch assigns |
| `p03` 001 | same | `> 0.0` to `> -1.0` | **Real gap, outside the input contract** | No stimulus has a negative delta. The source says `MAKE SURE > 0`. Killed by a stimulus with delta -0.5 (below) |
| `p04` 004 | 904 / 765 / 417 / 1200 | removed `tofTimer_Q := FALSE` in the reset branch | Equivalent | The stale `Q` is read only with `tofTimer_IN AND tofTimer_Q`. The next rising `IN` takes the start branch, which clears `Q` first |
| `r03` 001 | 1255 / 1142 / 691 / 1200 | `StepTimer_EN := FALSE` to `TRUE` in step 30's reset | Equivalent | That branch sets `StepNo := 0`, so `ENABLE` is false at the timer and `EN` is overwritten in the same scan |
| `r03` 003 | same | `AND` to `OR` in `StepTimer_TT` | Equivalent | `StepTimer_TT`: 5 writes, 0 reads, not an output |
| `r04` 004 | 1006 / 1064 / 493 / 1200 | removed the clamp `T0_ACC := DelayMs` | Equivalent | `ACC` is not an output and is read only by the accumulate and compare lines, which stop once `DN` is set. `DN` and `ACC` reset together |
| `s02` 001 | 1401 / 1519 / 370 / 1200 | `B_ET := T#0s` to `T#10ms` | Equivalent | `B_ET`: 3 writes, 0 reads, not an output |
| `s02` 003 | same | `-` to `+` in `B_ET` | Equivalent | Same variable |
| `s04` 001 | 1300 / 1153 / 711 / 1200 | `statBatchCounter_CV := 0` to `1` | Equivalent | Dead: inside `IF statBatchCounter_R`, and the line above sets `R := FALSE` as in the source |

### First sample, 6 mutants

| Program, mutant | Scans | Change | Verdict | Why |
|---|---|---|---|---|
| `u01` 000 | 988 / 920 / 403 / 1200 | `DT_STATE = 1` to `<> 1` in the disabled path | Equivalent | `DT_IN` is FALSE there, so the branch is dead |
| `u01` 001 | same | `DT_STATE := 2` to `1`, same place | Equivalent | Same dead branch |
| `u02` 003 | 919 / 814 / 426 / 1200 | `AND` to `OR` in `V2_W`'s start condition | Equivalent | While `IN` is false the state only toggles between 0 and 1 with `Q` false. A rising `IN` restarts the timer either way |
| `u02` 004 | same | removed `V1_W_ET := T#0s` | Equivalent | `V1_W_ET`: 3 writes, 0 reads, not an output |
| `u05` 005 | 1194 / 1269 / 744 / 1200 | swapped the P=2 and P=3 bodies in the "running but unavailable" loop | Equivalent | The loop only sets `CHANGED` if any pump matches, so order does not matter. `TMP_A` and `TMP_B` are reassigned before their next read |
| `u06` 000 | 788 / 847 / 456 / 1200 | `FLOW_SP < S_RAMP - 8.0` to `<=` | Equivalent | When equal, the branch assigns the value `FLOW_SP` already has |

### The two kills

Both are small stimuli written for this check, kept in the scratchpad, never added to the corpus.

| Mutant | Stimulus | Candidate against matiec | Mutant against matiec |
|---|---|---|---|
| `p01` 002 | 3 idle scans, 8 scans with Activate and Deactivate both TRUE and `cfgActTime` 20, `cfgDeactTime` 0, then 3 idle scans, 10 ms | equal, 14 scans | **12 divergences, first at scan 6: `Activated` expected TRUE, got FALSE** |
| `p03` 001 | 12 scans, delta 0.5, then 4 scans at -0.5, then 0.5, alpha 0.5, beta 0.25 | equal, 12 scans | **7 divergences, first at scan 5: `output` expected 39.09, got 42.04** |

`p01` 000, 003 and 004 stayed equal on the same zero-preset stimulus, and `p03` 000 stayed equal on the negative-delta one.

## p01: is the stimulus weak?

**Mostly no. The high survival comes mainly from where the mutants landed. There is one real hole: no stimulus uses a zero preset.**

Why 4 of 5 survived:

- The source calls `TransitionDelay(IN := FALSE)` on entry to each state, and calls it again with the real input. The model inlined the TON body four times: entry reset and normal call for each of 2 states.
- All 4 survivors are in the state-1 entry copy, algorithm lines 57 to 67, where `IN` was set to FALSE just above. In that copy the `STATE = 1` branch is dead.
- `TransitionDelay_ET` is written 12 times and never read.
- So any random mutant has a good chance of landing in code that cannot affect an output.

What else was measured:

- `corpus_hard/mutation_results.json` has `p01` at 34 available mutants, and `docs/HARD_CORPUS.md` gives 30 of 30 counted mutants detected on the source. That is a different experiment, on matiec.
- A fresh sample of 20 mutants of the same candidate, `--seed 7`, ran on all three scored stimuli: **12 killed, 8 survived**.
  - 7 of the 8 are in entry-reset copies, or write only the unread `ET`: mutants 001, 003, 004, 008, 012, 015, 019.
  - The eighth, mutant_005, swaps the IF and ELSE bodies in the state-0 entry copy. It is the same gap as `p01` 002. A stimulus with Activate TRUE from scan 0 and `cfgActTime = 0` kills it (`compare` exit 1).
  - The 12 killed include removing `vState := 1`, removing `TransitionDelay_PT := cfgActTime`, and changing the live timer's comparison.
- One useful detail: mutant_000 of that sample (`<=` to `<` on the live timer) was killed by the tuning and held-out stimuli and survived `heldout_stimulus_2.json` alone. There the period is 7 ms and the presets are 36 and 57, so exact equality never happens. The stimuli complement each other.
- `heldout_stimulus_2.json` holds both `cfg` times constant, 36 and 57, across all 832 scans.

What the stimuli do not do: no `cfgActTime` or `cfgDeactTime` of 0 in any scored stimulus, or in the random stimulus. The values used are 20, 30, 36, 40 and 30, 57, 60, 80. `docs/CORPUS.md` records that a TON with `PT = 0` takes one whole scan, so this is a real corner and it is not exercised on `p01`.

Open and not done: I did not check the same corner on other programs' scored stimuli. This file changes no stimulus. Adding one would change the manifest (`st2fb/llm/manifest.py`), so `hard_check` would have to pass again, and since it would come after seeing the model's results, it should be declared as such and the affected runs repeated.

## Fuzz, unscored and beyond the corpus's value ranges

For 14 programs with survivors, I made one 1500-scan stimulus from each tuning stimulus. It widens the values: REAL inputs can be 0 or negated, and time-like inputs can be 0 or one scan period. It is not part of any score. It deliberately breaks some programs' input contracts.

| Check | Result |
|---|---|
| Mutant against unmutated candidate, on FORTE | All equal except `p01` 002 (64 divergences), the gap above. `p03` could not be run: see below |
| Candidate against matiec | 11 of 14 equal. `p02` and `u06` differ (below). `p03`: matiec's trace hit `-inf`, which `reference_run` refuses to write |

The two differences do not look like logic errors in the model's code. I compared `p02`'s algorithm with the source line by line, and its text matches.

## Side findings

These came up during this work. None changes a published score. Each is a limit on what "equal" means.

1. **Division by zero differs between the two sides.** FORTE's `DivOperation`, in the image at `/forte/core/include/forte/iec61131_functions/func_DIV.h`, logs `Division by zero!` and returns 0. matiec's generated C divides REAL values as C floats, which should give an IEEE infinity. The `-inf` that `reference_run` refused on the `p03` fuzz fits that, but I did not trace it to one division. `p03`'s source masks this with `SEL`, so the scored stimuli do not show it. An FB without a guard can pass here. Another runtime may behave differently. I did not test EAE, which is not available in this project.
2. **`LIMIT` with `MN > MX` differs.** On the `p02` fuzz, 352 scans differ, and every one has `MinLoopOutput > MaxLoopOutput`. At scan 140: `MN` 10, `MX` 0, matiec 10.0, FORTE 0.0. The scored stimuli never have `MN > MX`.
3. **A REAL within tolerance can flip an INT.** On the `u06` fuzz, one scan of 1500: `VALVE_PCT` 50.9132652 against 50.9132690, a relative difference near 7.5e-8, well inside 1e-5. Then `REAL_TO_INT(VALVE_PCT * 276.48)` gives 14076 against 14077, and integers compare exactly. A correct FB could fail on this. The cause of the REAL difference was not traced.
4. **Mutation sampling is a small sample of the candidate's text, including its dead code.** The model's inlining creates dead copies of timer bodies, for example `tmr_a` in `14_batch_filling` and the `IN := FALSE` copies in `p01` and `u01`. A survival rate on these files says less about the stimuli than the same rate on the source.
5. **`docs/LLM.md` is stale.** Line 6 still says no model has run on `corpus_hard/`. Not changed here, since this task allows only this one file outside `study/`.

## Reading check of the candidates

Files are under `results/hard_2026-11-07/*/candidates/claude-sonnet-5-5/`. They are byte-identical to `build/llm_hard/reports/` (`diff -rq`). Sonnet 5.5 wrote them. The source and the reference were read side by side with them.

| Candidate | How read | Found |
|---|---|---|
| `s05_lead_lag_array` | Line by line against `program.scl` and `reference.st` | Faithful. The record array became `av1`..`av3`, unused `runTicks` dropped. `FOR` with `CONTINUE` and `EXIT` became `WHILE` with a `done` flag. `statPump[MAX(o_lead, 1)]` became an IF chain. Wrapper ECC: START, RUN |
| `r03_sequence_aoi` | Line by line against `program.l5k` and `reference.st` | Faithful to the dialect's reading. `RES(StepTimer)` became 4 assignments. `StepTimer_EN` plays the part of the reference's `Step_PREV`, including the reset. `TaskPeriodMs` is used, not a constant. `200` is from the source. Wrapper ECC. First attempt failed: see below |
| `x01_pump_station` | Skim: ECC, the first 130 algorithm lines against the source, and a script over the pump blocks | Wrapper ECC, one algorithm, 610-line file. `REPEAT` and the `PREFERENCE` and `VIEW` arrays were lowered to `FOR` and IF chains. Pump blocks 1, 2, 3 are the same 94 lines after renaming, and block 3 is followed by the output copy. **Not read line by line** |
| `14_batch_filling` | Full, against `corpus/14_batch_filling/program.st` | Faithful. 11 ECC states, matching the report. Abort, CU edge, timer and `PV := 1000` all kept. `tmr_a` has a dead expiry branch |
| `20_pump_station_supervisor` | Full, against the source | Faithful. 12 ECC states, matching the report. W5 has no `NOT AUTO_MODE` exit, matching `STATE_NO <> 5` in the source. Filter, SR, R_TRIG, TON and pulse `WHILE` all kept |
| `13_case_sequencer` | ECC and all algorithms, against the source | Faithful. `4..6` became 3 states, and `SEQ + 1` became literals 5, 6, 7. Abort goes to `ABORT_STEP`, then W8 |
| `06_star_delta` | ECC and the small algorithms | See below |
| `p01`, `p04`, `s02`, `s04`, `u01`, `u02`, `u05`, `u06` | Around each surviving mutant, and whole for `p01`, `p04` | Nothing suspicious |

`p02` and `p03`: algorithm read against the source. Logic not compared with the source by a reader, and covered only by the script below: `r01`, `r02`, `r04` beyond its first timer, `s01`, `s03`, `s06`, `s07`, `s08`, `u03` beyond its ECC, `u04`.

### ECC claims, confirmed by reading

`benchmark.json` says 3 of 4 are `ecc_persistent`, by a static metric. Reading agrees on the three:

- `13`, `14`, `20`: each position has a waiting state with no actions (`W1`.., `START`). The ECC stops there between REQ events and takes `REQ` to a step state that runs that position's own algorithm. Guards such as `[STATE_NO = 2]` read a value assigned by the algorithm in the same scan. In `20`, each step algorithm starts by writing its own number to `STATE_NO`, so the output follows the ECC and not the reverse. Control state counts 9, 5, 6 match the report.
- Timers inside these FBs still keep their own `*_STATE` variables. "Persistent" is about the control position, not about all state.
- `06_star_delta`: `START` and `WAIT_RUN` do hold the `RUN_CMD` latch in the ECC, but both paths then run the same `body`, and only one line differs (`run_on`, `run_off`). The metric fails it on `C5: every control state runs the same algorithms`. It is a thin two-position latch. I agree with not counting it.
- These forms were asked for, with a worked example: `prompt_files/form_ecc_persistent_v1.md` and `example_persistent_v1.fbt`. And `corpus_hard/ecc_persistent/*/control.fbt` already has working solutions with the same property. So this shows the model can follow that instruction here, not that only a model can produce this form.

### Scan-count special-casing and test-specific hacks

**None found.** What that rests on:

1. The reading above.
2. A script over all 27 files. Time literals not in the source: none except `T#0s`. Numeric literals not in the source: only `2`, `3`, `4`, `5`, `6`, `8`, `128` and `27648.0`. Traced: `2` is the TON state code from the prompt's matiec body, and also a `CASE` label in `u03`. `5` and `6` come from `SEQ + 1` in `13`. `4`, `8`, `128` are bit weights in `r04` and `s06`. `27648.0` is the source's range as a REAL in `s02`. `3` is a `CASE` label in `u03`. Not one looks like a scan number or a stimulus value.
3. `ST2FB_NOW` appears only in 4 shapes across all 15 files that use it: `:= ST2FB_NOW + SCAN_DT`, `START_TIME := ST2FB_NOW`, `START_TIME + PT <= ST2FB_NOW`, and `ET := ST2FB_NOW - START_TIME`. It is never compared with a constant.
4. Variables that count on each scan: only the source's own (`TICKS` in `u05` and `x01`).
5. The random 1200-scan stimulus equalled matiec on all 27 candidates, and the fuzz on 11 of 14. A candidate fitted to the tuning data would be likely to fail those, as well as the held-out stimuli.

Limits of this conclusion: a script and a partial reading cannot rule out a hack in a file nobody read line by line. It lowers the chance, and it is not proof.

Small oddities, not hacks: all 27 say `Author="st2fb" Date="2026-11-06"`, and 25 say `Comment="Migrated from IEC 61131-3 ST"` even for SCL sources. That boilerplate comes from the prompt's example, so this metadata means nothing.

### The two repairs

Parsing every cached reply in `build/llm_hard/cache/` with the current `fbt.parse_fbt` gives exactly 2 errors out of 29, both first attempts, and both the same: `<InternalVars> must be inside <BasicFB>, not inside <InterfaceList>`. They are `r03_sequence_aoi` and `14_batch_filling`. Both second attempts pass. This is the same fault as the 2026-11-06 failures on `18_pump_station_rotation`, now with a message that names it.

## What this file does not establish

- It does not prove any candidate correct. The verdicts say what these mutants and stimuli can and cannot see.
- Nothing here was run on TIA Portal, Studio 5000, EAE, a real PLC, or any hardware. The oracle for vendor programs is a hand-written `reference.st`.
- The corpus is largely self-authored, and the whole project, including this analysis, was produced with AI tooling.
- The scratch files behind the first sample and the probes are in a session scratchpad and may not survive it. To reproduce: run `st2fb.mutate fbt <candidate> --count 6 --seed 61499` for the seven first-sample programs, and rebuild the probe stimuli from the descriptions above.
