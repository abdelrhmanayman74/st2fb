# Source and changes

- Project: https://github.com/anjlab/codebox
- Commit: baec19e84109f402a5e7e7a2b4cdd752e82298a5
- File: `AnjLabCodeBox.xml`, POU `DebounceBool`, author named in the file as Sergey A Glukhov
- Licence: Apache License 2.0, `LICENSE` in this directory. Copyright 2025 AnjLab.

This file is modified from the original (Apache-2.0 section 4). Changes, all to make it compile as text under matiec:

- The declaration was rebuilt as ST from the PLCopen XML interface. Variable documentation was dropped.
- The initial values `TIME#30ms` of `onDelay` and `offDelay` were dropped, since the harness writes every input on every scan.
- `//` comments became `(* *)`.
- A header comment with the copyright was added.

Compared with the upstream XML at this commit on 2026-11-07, with comments stripped and whitespace normalised: the body is identical. That is a text comparison, and it is all that "unchanged" means here.
