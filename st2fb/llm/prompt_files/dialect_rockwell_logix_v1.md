## Source dialect: Rockwell Logix structured text, Add-On Instruction style

The source is an Add-On Instruction in a text form. It is compared with a reference that gives the following meaning to it, so follow this reading rather than
any other. Use only standard ST in your output.

Layout and names:

- `ADD_ON_INSTRUCTION_DEFINITION Name`: the FB type name is `Name`. PARAMETERS with `Usage := Input` are VAR_INPUT, and those with `Usage := Output` are VAR_OUTPUT.
  Keep their names exactly as spelled. LOCAL_TAGS are internal variables. The body is in ST_ROUTINE. EnableIn and EnableOut do not exist.
- Keywords may be lower case. `//` and `/* */` are comments. `&` is AND. BOOL values are written 1 and 0.
- `a [:= b;` is a non-retentive assignment, which in a running routine is `a := b;`.
- `x.n` on a DINT is bit n of it. Read it with `(x / 2^n) MOD 2 = 1`, which holds for the non-negative values used here. Assigning bit n of a word that was just set to 0
  adds `2^n` when the value is true.

Time and instructions. These blocks do not use SCAN_DT, so do not add it. A block with a timer has a DINT input, TaskPeriodMs, with the period of one scan in milliseconds, and all
`.PRE` and `.ACC` members are DINT milliseconds:

- FBD_TIMER, called as `TONR(t)` with members TimerEnable, PRE, EN, TT, DN and ACC. On each call: EN := TimerEnable. If EN is true and was also true at the previous call, and DN is false,
  then ACC := ACC + TaskPeriodMs, and if now ACC >= PRE then ACC := PRE and DN := TRUE. So the first enabled call leaves ACC at 0, and DN stays set until the timer is disabled or reset.
  If EN is false: ACC := 0 and DN := FALSE. Then TT := EN AND NOT DN.
- FBD_COUNTER, called as `CTUD(c)` with members CUEnable, PRE, ACC and DN. On each call: on a rising edge of CUEnable, ACC := ACC + 1, without stopping at PRE. Then DN := ACC >= PRE.
- FBD_ONESHOT, called as `OSRI(o)` with members InputBit and OutputBit: OutputBit is true on the call where InputBit rises.
- `RES(t)` on a timer sets ACC to 0 and EN, TT and DN to FALSE, and forgets the previous EN, so the next enabled call counts as the first. On a counter it sets ACC to 0 and DN to FALSE,
  and keeps the previous CUEnable.
- Members read before the instruction is called in a scan hold their values from the last call.
