## Sources beyond the target's scope

The source below may use constructs that a Basic FB algorithm cannot express. Keep its behaviour and rewrite those
constructs into the form above. Nothing may be left out because it is hard to express. In particular:

- A file can hold helper FUNCTIONs and FUNCTION_BLOCKs. The block to migrate is the one marked `(* st2fb:dut *)`, or the only
  FUNCTION_BLOCK if there is no mark, and its VAR_INPUT and VAR_OUTPUT are the interface. Everything else is inlined. Every instance
  of a helper block keeps its own state, as its own internal variables.
- Arrays and structures become separate internal variables. An indexed access becomes a CASE or IF on the index. Declared initial
  values must be kept.
- RETURN leaves only the block or function it is in, and skips everything after it in that block for this scan. EXIT leaves the
  innermost loop. REPEAT runs its body before the first test. The target has none of these three, so rewrite them with
  IF, WHILE and flags.
- Variables keep their values between scans, except that VAR_TEMP values must not be relied on across scans. VAR CONSTANT is a
  constant.
- SCAN_DT is added if the source or any helper uses a timer, as above.

Limits of the target that matter here: REAL_TO_INT and REAL_TO_DINT behave like the reference's and need no rewriting. `**` is available.
There is no conversion between TIME and any number, so write time arithmetic with TIME values only.
