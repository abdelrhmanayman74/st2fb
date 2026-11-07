## Source dialect: Siemens SCL, TIA Portal style

The source is an SCL function block. It is compared with a reference that gives the following meaning to SCL, so follow this
reading rather than any other. Use only standard ST in your output.

Layout and names:

- `FUNCTION_BLOCK "Name"`: the FB type name is `Name`, without quotes. TITLE, AUTHOR, FAMILY, NAME, VERSION, `{ ... }` attributes and
  `//` comments have no effect. BEGIN starts the body.
- `#name` is the local variable `name`. Keep every VAR_INPUT and VAR_OUTPUT name exactly as spelled, without `#`.
- Types: Bool, Int, DInt, UInt, Real and Time are BOOL, INT, DINT, UINT, REAL and TIME.
- VAR and VAR_TEMP are internal variables, VAR CONSTANT is a constant. REGION and END_REGION have no effect.
- `Array[a..b] of T` and `Struct` are arrays and structures, as described above.

Instructions:

- Timers: TON_TIME is TON, TOF_TIME is TOF, TP_TIME is TP. An IEC_TIMER instance `t` is called as `#t.TON(...)` and behaves as TON,
  and its outputs are read as `#t.Q` and `#t.ET`. They follow the standard bodies given above, and need SCAN_DT.
- CTU_INT is CTU. R_TRIG is as given above.
- `NORM_X(MIN, VALUE, MAX)` is `(VALUE - MIN) / (MAX - MIN)` as REAL, and `SCALE_X(MIN, VALUE, MAX)` is `VALUE * (MAX - MIN) + MIN`.
- `LIMIT(MN, IN, MX)`, `MIN(IN1, IN2)`, `MAX(IN1, IN2)` are the standard functions with named arguments. `SEL(G, IN0, IN1)` gives IN1 when G is TRUE.
- `ROUND(x)` is REAL to DINT, to the nearest integer, and exactly half goes to the even neighbour. It behaves like REAL_TO_DINT. `SQR(x)` is `x * x`.
- `T_ADD(IN1, IN2)` and `T_SUB(IN1, IN2)` are TIME + TIME and TIME - TIME.
- `a += b;` is `a := a + b;`. CONTINUE goes to the next iteration of the innermost loop.
- `x.%Xn` is bit n of a Word, read or written. Word exists only inside the block: convert it with arithmetic, since `(v / 2^n) MOD 2 = 1` reads a bit of a
  non-negative integer. UINT_TO_WORD and WORD_TO_UINT keep the bits, and `16#0000` is a hexadecimal literal.
