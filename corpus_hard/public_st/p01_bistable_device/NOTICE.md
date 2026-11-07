# Source and changes

- Project: https://github.com/tkucic/plc_hello_mixing_tank
- Commit: 17e0213b1c7c46fd44ff7d9a52a6bb9e500d65de
- File: `plc_hello_mixing_tank.xml`, POU `GenericBistableDeviceModel`
- Licence: MIT, `LICENSE` in this directory. Copyright (c) 2021 Toni Kucic. The project describes itself as educational.

Changes, all to make it compile as text under matiec:

- The declaration was rebuilt as ST from the PLCopen XML interface. Variable documentation was dropped.
- `;` added after `END_IF` and `END_CASE`.
- The XML escapes in the body became plain text.
- A header comment with the copyright was added.

Every initial value of the upstream interface is kept: `cfgActTime` and `cfgDeactTime` `TIME#1s0ms`, `vState` `0`, `vStateOld` `3`. An earlier version of this file dropped them, including the `3` that makes the first scan run the entry action of state 0. The harness writes every input on every scan, so the two input values have no effect here.

Compared with the upstream XML at this commit on 2026-11-07, with comments stripped and whitespace and the added `;` normalised: the body is identical, and the declared names, types and initial values match. That is a text comparison, and it is all that "unchanged" means here.

`regression_zero_preset.json` was added after the model benchmark, to cover a zero `cfgDeactTime` that no scored stimulus uses. It is not part of the score.
