# Corpus and reference semantics

## Status of this corpus

**This corpus is self-authored and therefore not an independent benchmark.** The same project wrote
the programs, their stimuli and the migration tool. Results on it show the tool works on these
programs. They do not show how it does on industrial code it has never seen. The programs are
realistic in shape but none of them comes from a real plant.

Every program and stimulus uses only the v1 scope in `docs/DESIGN.md`: BOOL, INT, DINT, UINT, REAL,
TIME; assignment, IF, CASE, FOR, WHILE; TON, TOF, TP, R_TRIG, F_TRIG, CTU, CTD, SR, RS. No standard
functions and no type conversions are used.

Stimuli come from `corpus/generate_stimuli.py`, seeded, and regenerating gives identical files. Each
has a directed part, which walks the branches and sits exactly on comparison boundaries, and a random
part. REAL inputs are multiples of 1/8, so they are exact in binary. `00_latch` is hand-written.

| Program | Scans | scan_ms | Exercises | matiec |
|---|--:|--:|---|---|
| 00_latch | 7 | 10 | hand-written contract example: IF, edge detect by hand | compiles and runs |
| 01_motor_start_stop | 303 | 10 | seal-in, latched trip, UINT | compiles and runs |
| 02_tank_hysteresis | 453 | 100 | REAL thresholds | compiles and runs |
| 03_scaling_clamp | 379 | 10 | REAL arithmetic, clamping | compiles and runs |
| 04_parts_counter | 393 | 10 | CTU, R_TRIG, DINT | compiles and runs |
| 05_alarm_debounce_ack | 519 | 10 | TON, TOF, R_TRIG, TIME inputs | compiles and runs |
| 06_star_delta | 767 | 10 | chained TON, TIME literal, TIME output | compiles and runs |
| 07_conveyor_interlock | 1287 | 10 | TON, TOF, staggered start and stop | compiles and runs |
| 08_first_out_alarm | 403 | 10 | nested IF, INT | compiles and runs |
| 09_totalizer | 542 | 100 | FOR, WHILE, REAL, DINT | compiles and runs |
| 10_valve_feedback | 712 | 10 | two TON, latched fault, TIME output | compiles and runs |
| 11_ramp_generator | 491 | 50 | REAL, nested IF | compiles and runs |
| 12_pid_loop | 680 | 100 | REAL, anti-windup, manual mode | compiles and runs |
| 13_case_sequencer | 1134 | 10 | CASE with range and ELSE, conditionally called TON | compiles and runs |
| 14_batch_filling | 981 | 10 | CASE, REAL, TON, CTU, R_TRIG | compiles and runs |
| 15_duty_standby | 684 | 10 | F_TRIG, SR, TON, UINT | compiles and runs |
| 16_pump_station_level | 1418 | 100 | pump station: REAL, TON, F_TRIG, DINT | compiles and runs |
| 17_pump_station_protection | 1346 | 10 | pump station: RS, TP, TOF, TON, CTU, TIME output | compiles and runs |
| 18_pump_station_rotation | 1251 | 10 | pump station: nested FOR, CASE, XOR, DINT, self-resetting TON | compiles and runs |
| 19_auto_restart | 1133 | 10 | CTD, RS, R_TRIG, TON | compiles and runs |
| 20_pump_station_supervisor | 1990 | 100 | pump station, main demo: CASE, FOR, WHILE, SR, TON, R_TRIG, REAL | compiles and runs |

Changes needed to compile under matiec, all on the first compile attempt:

- `12_pid_loop`: a local variable called `INTEGRAL` was rejected, because that is the name of a function
  block in matiec's standard library (`lib/integral_st.txt`). Renamed to `I_TERM`.
- `15_duty_standby` and `20_pump_station_supervisor`: read `.Q` of an SR instance. The output of SR and
  RS is `Q1`. Author error, caught by matiec.

No program was changed to raise a mutation score. Only stimuli were changed. See `docs/MUTATION_RESULTS.md`.

Regenerate the stimuli and check every program compiles and runs with:

    python3 corpus/generate_stimuli.py
    python3 -m unittest tests.test_validation_reference.Corpus

## Mutation testing

`docs/MUTATION_RESULTS.md` has the numbers. To read them:

- The mutants are simple single edits, and a high rate says the comparison and stimuli catch this kind of bug. It
  says nothing about bugs that a stimulus never provokes in a way no single-edit mutant resembles.
- 78 of the 79 compile-failed mutants are removals of the only statement in a branch. matiec rejects an empty branch,
  even with a lone `;` in it. They are not counted, so "remove the only statement of a branch" is not measured
  directly. The other one is `2147483648`, out of range for DINT.
- Programs were not changed between the runs, so "before" and "after" use the same mutants. Only stimuli changed.

The first exhaustive run showed real stimulus weaknesses, which were then fixed:

- `20_pump_station_supervisor`: the level filter only approaches its input, so a raw level of 3.0 never reached the
  start level of 3.0. The proof timer therefore never fired, and removing it went unnoticed. Failure to prove was
  never exercised. The stimulus now has a directed walk that lands exactly on each threshold, and it covers
  failure to prove, a lead trip in each state, and feedback from the lag pump only.
- `09_totalizer`: 8 Newton iterations had converged at every DP used, so the iteration count could not be seen. A very
  large DP now shows it.
- `12_pid_loop`: the deadband hid small errors while saturated. The stimulus now has a phase with no deadband.
- `13_case_sequencer`: nothing showed that the abort state resets the step timer. Added an abort with HOLD running
  into the next timed step.
- `14_batch_filling`: nothing showed that abort clears the result flags. Added an abort after each result.
- `03_scaling_clamp`: nothing set the over-range flag just before the range went bad. Added.

## Scan cycle of the reference runner

`st2fb/reference_run.py` does this for scan `i`, counting from 0:

1. `__CURRENT_TIME := i * scan_ms`
2. Write that scan's `VAR_INPUT`s into the FB instance.
3. `config_run__(i)`, which executes the FB body exactly once.
4. Read the `VAR_OUTPUT`s and record them with `t_ms = i * scan_ms`.

So time advances between scans, the first scan sees time 0, and the clock does not move during a scan:
every timer called in a scan reads the same value.

Only time differences are observable in the v1 scope, because every timer computes
`CURRENT_TIME - START_TIME`. Starting the clock at 0 or at `scan_ms` gives the same outputs.

`__CURRENT_TIME` is the global from matiec's `iec_std_lib.h`. The driver is the only writer. No wall clock
is read anywhere. The container has no network, and gcc runs with `-fwrapv -ffp-contract=off`.

## Observed timer semantics

Observed from matiec's `lib/timer.txt` compiled at commit 3a41303, and pinned by
`tests/test_validation_reference.py` with values worked out by hand from the library source. In
these tables `scan_ms = 10`, `PT = 30 ms`, and each column is one scan.

### TON

    IN  0 1 1 1 1 1 0
    Q   0 0 0 0 1 1 0
    ET  0 0 10 20 30 30 0

- The rising-edge scan records the start time. ET stays 0 and Q stays FALSE on that scan.
- Q rises on the first scan with `START + PT <= now`, when ET becomes PT, so `PT` is reached exactly
  `PT / scan_ms` scans after the edge scan.
- `IN` falling clears Q and ET on that same scan.
- `PT = 0`: still takes one scan, since the edge scan does not test expiry (Q: 0 0 1 1 for IN 0 1 1 1).
- `PT` not a multiple of the scan: Q rises on the next scan boundary and ET shows PT, not the elapsed
  time (`PT = 25`: ET is 0, 10, 20, 25, 25).
- `IN` TRUE on the very first scan is a rising edge, since `PREV_IN` starts FALSE.
- Expiry is tested against the current `PT` each scan, so lowering PT mid-count can expire the timer. This one is read
  from `lib/timer.txt`, and no test pins it.

### TOF

    IN  0 1 1 0 0 0 0 1
    Q   0 1 1 1 1 1 0 1
    ET  0 0 0 0 10 20 30 0

- The falling-edge scan records the start time, ET stays 0, and Q stays TRUE.
- Q falls on the first scan with `START + PT <= now`, and ET stays at PT until IN rises.
- IN rising during the delay cancels it: ET returns to 0 and Q stays TRUE.
- With IN FALSE from the first scan, Q is FALSE and no delay runs.

### TP

    IN  0 1 1 1 1 1 0 0 0
    Q   0 1 1 1 0 0 0 0 0
    ET  0 0 10 20 30 30 0 0 0

- Q rises on the edge scan, with ET 0. It falls on the first scan with `START + PT <= now`.
- IN changes during the pulse are ignored and do not retrigger it.
- After expiry ET holds PT while IN stays TRUE, and goes to 0 once IN is FALSE. A new pulse needs a new
  edge after that.
- If IN is already FALSE on the expiry scan, ET goes straight to 0 in that scan and PT never appears:

      IN  0 1 0 1 0 0 0
      Q   0 1 1 1 0 0 0
      ET  0 0 10 20 0 0 0

## What this means for the SCAN_DT lowering

**A timer does not count while it is called. It compares an absolute clock with a start time.** A timer
that is not called on some scans still sees that time pass. `tests/test_validation_reference.py` pins
this: with IN TRUE and calls on scans 0, 1, 5 and 6, ET goes 0, 10, 10, 10, 10, 30, 30 and Q rises on
scan 5. `13_case_sequencer` depends on it: its step timer is not called during HOLD.

So a lowering that adds `SCAN_DT` to an elapsed counter inside the timer call will diverge there. The
faithful lowering is one internal `CLOCK : TIME`, incremented by `SCAN_DT` once at the top of every scan
before any other statement, plus the state machine from `lib/timer.txt` copied literally, with
`CLOCK` in place of `CURRENT_TIME`. The clock starts one step ahead of the reference clock, which is
harmless, since only differences matter.

The library's state machines are short and the corner cases above all come from them, so reading
`lib/timer.txt` is the shortest route to matching them.

## Other observed semantics a migration must match

- **F_TRIG fires on the first scan if CLK is low.** The library is `Q := NOT CLK AND NOT M; M := NOT CLK;`
  and M starts FALSE. This is why `ALTERNATIONS` in `15_duty_standby` and `CYCLES` in
  `16_pump_station_level` read 1 from the first scan. R_TRIG has no such effect.
- **CTU, CTD** (read from `lib/counter.txt`, and exercised by the corpus rather than pinned by a dedicated test)**:** each owns an R_TRIG on its count input. `R` or `LD` has priority over counting. Q is
  recomputed every call from `CV`. The count saturates at PV for CTU and at 0 for CTD.
- **SR** (read from `lib/bistable.txt`, as is RS)**:** `Q1 := S1 OR (NOT R AND Q1)`, set wins. **RS:** `Q1 := NOT R1 AND (S OR Q1)`, reset wins.
  The outputs are called Q1, not Q.
- **Standard FB outputs are read as they stood after the last call**, so reading `T1.Q` before calling
  `T1` in a scan sees the previous scan's value. `04`, `17`, `18` and `20` read before they call.
- **Integer arithmetic is C arithmetic.** Generated code evaluates an INT expression in C `int` and truncates on
  assignment. Observed: `32767 + 1` assigned to INT is -32768; `(20000 * 2) / 2` assigned to INT is 20000,
  because the intermediate does not wrap. DINT and UINT wrap (`-fwrapv`), with `0 - 1` assigned to UINT
  being 65535. `/` truncates toward zero and `MOD` takes the sign of the dividend: `-7 / 2 = -3`,
  `-7 MOD 2 = -1`, `7 / -2 = -3`, `7 MOD -2 = 1`. An integer divide by zero kills the process with SIGFPE. No corpus
  program divides integers, and none of their outputs comes near an integer limit on these stimuli.
- **FOR:** on normal exit the loop variable is one step past the bound. If the bound is below the start, the body
  does not run and the variable holds the start value (observed with `FOR I := 1 TO B` and B = -2, I = 1).
- **TIME literals are often 1 ns short.** matiec builds them through `long double` and truncates. Measured on
  x86-64 at this commit: 28732 of the 60000 multiples of 10 ms up to 600 s are stored inexactly, for
  example `T#130ms` is 129999999 ns, while `T#100ms` is exact. Effects:
  - Timers are unaffected on a scan grid: `START + PT <= now` gives the same scan either way.
  - A TIME output of a literal, including `ET := PT`, prints correctly, because the driver rounds to the
    nearest ms. TIME inputs from a stimulus are exact.
  - A direct comparison with a literal can differ from exact arithmetic: with ET exactly 130 ms, `ET > T#130ms` is TRUE
    and `ET <= T#130ms` is FALSE under matiec. The corpus avoids such comparisons, so a migration is not
    required to reproduce this. Any new program that makes one would expose it.
- **REAL_TO_INT and REAL_TO_DINT round half to even.** `lib/C/iec_std_lib.h` adds 0.5 and fixes up exact integers, so 1.5 and 2.5 both give 2, and -0.5 gives 0. FORTE gives the same on every value tried in `tests/test_hard_corpus.py`.
- **`iec_lib_*` are hooks that the platform has to provide.** `iec_std_lib.h` declares `iec_lib_fmod`, `iec_lib_pow`, `iec_lib_sqrt` and others without defining them, so REAL_TO_INT, REAL_TO_DINT, `**` and the math functions did not link until the driver in `reference_run` defined them, as plain calls to the C library. No corpus program uses them.
- **TIME_TO_DINT and friends count seconds under matiec.** `__time_to_int` returns `tv_sec`, and DINT_TO_TIME takes seconds. FORTE at the pinned commit has no such functions at all, so no program in either corpus converts between TIME and a number.
- **matiec's own limits, found while writing `corpus_hard/`.** `ARRAY OF TON` is rejected by iec2c. An `ARRAY` in `VAR_TEMP` makes iec2c write C that gcc rejects. `//` comments are a syntax error. `MID`, `LOG`, `LEFT` and `STEP` cannot be variable names.
- **`TIME + TIME` and `TIME - TIME` in source ST need a workaround.** At this commit iec2c emits `_____time_add`,
  a name that does not exist, so gcc rejects the program. `reference_run` passes `-D_____time_add=__time_add` and the
  same for `sub`, which route the calls to matiec's own library functions. Nothing else in the generated
  code is changed, and no corpus program uses this: their TIME values only go through timers and assignment.
- **REAL is IEEE 754 single.** The driver prints `%.9g`, which round-trips, and writes REAL with a decimal point, so that
  `st2fb.compare` treats the column as REAL. A non-finite REAL is a run failure, since JSON cannot hold it.

## Runner failure modes

`reference_run` exits non-zero, and writes nothing, in these cases: a stimulus that does not list exactly the
`VAR_INPUT`s on each scan, a value of the wrong type or out of range, iec2c or gcc rejecting the program, a crash or
a run over 10 s, and a non-finite REAL.

## The compare report

`report.json` has the contract's fields plus `shape_errors`, a list of structural problems. See the module docstring
of `st2fb/compare.py` for the rules. Exit status is 0 for equal, 1 for different, 2 for an unreadable trace.
