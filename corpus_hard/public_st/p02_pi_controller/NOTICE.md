# Source and changes

- Project: https://github.com/Intecre/twincat-utils
- Commit: cd7a087d885d2d415e5eeb497bfe3237843f3fed
- Files: `IntecreUtilities/IntecreUtilities/IntecreUtilities/Utilities/PI Controller/FB_P_Control.TcPOU`, `FB_I_Controller.TcPOU`, `FB_PI_Controller.TcPOU`
- Licence: MIT, `LICENSE` in this directory. Copyright (c) 2022 Intecre Ltd. The clone was shallow, so when these files were written was not checked.

This is not the same program as upstream. Changes:

- The ST was extracted from the `.TcPOU` XML, and the three blocks placed in one file, helpers first, with `END_FUNCTION_BLOCK` added.
- `(* st2fb:dut *)` was added before `FB_PI_Controller`, to mark the block under test.
- **`LREAL` became `REAL`** on every variable, since the harness interface has no LREAL. Every computation here is single precision, so the numbers differ from what upstream computes.
- **`T_Task` was removed.** Upstream declares `task : T_Task`, calls `task.SetToThisTask()`, and multiplies by `task.CycleTimeInSecs`. Here that declaration and call are gone, and `FB_I_Controller` and `FB_PI_Controller` each have a new input, `CycleTimeInSecs`, passed down. So the cycle time is whatever the stimulus says, and the interface of the block has one more input than upstream.
- `1000` and `-1000` in the initial values of the integral limits became `1000.0` and `-1000.0`. `0` in a REAL context became `0.0` (`Ki <= 0`, `Term := 0`, `integralComponent := 0`). `1` and `60` in `SEL` became `1.0` and `60.0`.
- `//` comments became `(* *)`.
- `;` added after `END_IF` where it was missing.

Everything else was compared with the upstream files at this commit on 2026-11-07, with comments stripped and whitespace normalised, and is the same text.
