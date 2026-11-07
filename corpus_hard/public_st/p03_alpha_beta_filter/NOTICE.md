# Source and changes

- Project: https://github.com/Intecre/twincat-utils
- Commit: cd7a087d885d2d415e5eeb497bfe3237843f3fed
- File: `IntecreUtilities/IntecreUtilities/IntecreUtilities/Filters/FB_AlphaBetaFilter.TcPOU`
- Licence: MIT, `LICENSE` in this directory. Copyright (c) 2022 Intecre Ltd. The clone was shallow, so when this file was written was not checked.

This is not the same program as upstream. Changes:

- The ST was extracted from the `.TcPOU` XML, with `END_FUNCTION_BLOCK` added.
- **`LREAL` became `REAL`** on every variable, since the harness interface has no LREAL. Every computation here is single precision, so the numbers differ from what upstream computes.
- `//` comments became `(* *)`.
- `SEL(deltaInSecond > 0, 0, ...)` became `SEL(deltaInSecond > 0.0, 0.0, ...)`.

Everything else was compared with the upstream file at this commit on 2026-11-07, with comments stripped and whitespace normalised, and is the same text.
