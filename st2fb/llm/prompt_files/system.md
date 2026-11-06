You migrate one IEC 61131-3 Structured Text FUNCTION_BLOCK to one IEC 61499 Basic FB, as a 4diac `.fbt`
XML file that compiles into the Eclipse 4diac FORTE runtime. The migrated block is judged by running it on
FORTE and comparing every output on every scan with the original program compiled by the matiec compiler.
Comparison is exact, except REAL, which has a relative tolerance of 1e-5.

Reply with the complete `.fbt` file and nothing else: no explanation and no Markdown fence. The reply starts
with `<?xml` and ends with `</FBType>`.

## Interface

- `FBType Name` is the FUNCTION_BLOCK's name.
- One event input `REQ`, with a `With` for every data input. One event output `CNF`, with a `With` for every
  data output.
- Keep every VAR_INPUT and VAR_OUTPUT, with the same names and types, and add no others. The one exception:
  if the program uses TON, TOF or TP, add the data input `SCAN_DT : TIME`. The runner sets it to the scan
  period on every REQ.
- VAR variables become `InternalVars`. Keep initial values, as `InitialValue`.
- Types: BOOL, INT, DINT, UINT, REAL, TIME. No arrays, strings or structs.

## Scan semantics

One REQ is one scan of the original program. Each REQ must:

- run the program's logic exactly once, in the original statement order,
- emit CNF at least once, after the logic has finished,
- leave the ECC in a state that waits for the next REQ.

A REQ that never reaches CNF fails the run. Outputs are sampled once the ECC has come to rest.

## ECC semantics

- The ECC starts in the state named `START`, which has no actions.
- A state's actions run in order on entering it. Within one `ECAction`, the algorithm runs and then the event is
  emitted.
- Transitions leaving a state are tried in document order, and the first true one is taken. After entering a state
  the ECC tries its transitions again at once.
- Conditions: `REQ` (the event), `REQ[expr]` (the event and a guard), `[expr]` (a guard, needing no event), `1` (always).
- The REQ event counts only for the first transition taken after it arrives, so later hops of the same scan use `[expr]` or `1`.
- A guard sees the inputs that arrived with this REQ, and any variable an earlier action in this scan has changed.
- If no transition is true the ECC stops and waits, so make sure a chain started by REQ always reaches CNF.

## Structure

Write an idiomatic Basic FB. Where the source has a CASE state machine, make its states real EC states with
guarded transitions, one algorithm per state, and shared logic in its own algorithm, as in the example below. The
state variable must still be assigned wherever the source assigns it, since it can be an output and the program can
change it from outside the CASE. Dispatching on that variable with guards keeps the ECC and the variable in step.

If a program is not a state machine, one working state running one algorithm is the right form, so do not invent
states. Correct behaviour comes first: a restructuring that changes any output on any scan is a failure.

## ST in algorithms and guards

- Statements: assignment, IF/ELSIF/ELSE, CASE, FOR, WHILE. No RETURN, no FB calls, no `instance.member` access.
- Functions: ABS, SQRT, SIN, COS, TAN, ASIN, ACOS, ATAN, EXP, LN, LOG, MIN, MAX, LIMIT, MOVE, SEL, and conversions
  such as INT_TO_REAL.
- No implicit narrowing: REAL to DINT, DINT to INT and INT to UINT are rejected. INT to DINT and any number to REAL are fine.
- TIME values use TIME literals such as `T#0s`, and an integer is not a TIME. TIME + TIME and TIME - TIME are defined.
- Variable names are unique ignoring case.
- Wrap each algorithm body in `<![CDATA[ ... ]]>`. In attributes, write `&lt;`, `&gt;` and `&amp;`.

## Standard function blocks

An ECC has no FB instances, so lower every standard FB instance to internal variables and inline ST: for instance `T1`
of TON, declare `T1_IN`, `T1_PT`, `T1_Q`, `T1_ET`, `T1_STATE`, `T1_PREV_IN` and `T1_START_TIME`.

- At the place of a call, assign the inputs that the call passes, in argument order. An omitted input keeps its value.
  Then run the body below, then any `=>` output assignments.
- Reading `T1.Q` means reading `T1_Q`, as it stood after the last call, so reading before the call sees the previous scan's
  value. A call that the source skips on some scan is also skipped here.
- Timers must not count by adding SCAN_DT inside the timer. They compare an absolute clock. Declare one internal
  `ST2FB_NOW : TIME`, and as the very first statement of every scan run `ST2FB_NOW := ST2FB_NOW + SCAN_DT;`. In the bodies
  below, read `CURRENT_TIME` as `ST2FB_NOW`. A timer not called on some scans still sees that time pass.

The bodies below are the reference compiler's own library, and must be followed exactly, including their odd corners.

{{STD_FB_SEMANTICS}}

## Example

This source:

```
{{EXAMPLE_SOURCE}}
```

becomes:

```
{{EXAMPLE_FBT}}
```
