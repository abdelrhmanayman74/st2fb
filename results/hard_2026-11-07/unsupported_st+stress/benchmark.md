# LLM benchmark, hard corpus

`client`: `live`. Sets: unsupported_st, stress. Requested form: default. Prices as cached on 2026-10-06; check real cost against the Console.

A run passes only if its final candidate equals matiec on the tuning stimulus and on the held-out stimulus. Structure never decides a pass.
`Persistent` is the strict metric: control position is held by ECC state across REQ events. See `st2fb/llm/ecc_metric.py`. `Restructured` only counts states with actions.

These programs were written by this project, except public_st. SCL and Logix sources were never compiled by TIA Portal or Studio 5000, and the oracle for them is a hand-written
translation, so an error in the pairing would count against the model. Inspect a failure before assuming that the model is wrong. See `docs/HARD_CORPUS.md`.

- `unsupported_st`: self-authored plain ST outside the translator's scope.
- `stress`: self-authored, written by this project's AI tooling.

## Baseline tiers

Two deterministic comparators run on every program. `translator` is the current translator on what the model sees. `frontend+translator` puts `st2fb/vendor_frontend.py`, a small syntax rewrite
that never sees the reference, in front of it. `rejected` under `translator` means only that this parser or scope stopped, and it is the expected result here. A model's pass is compared with both tiers.

| Tier | Status | Programs | Which |
|---|---|--:|---|
| translator | rejected | 7 | u01_sensor_voting, u02_valve_manifold, u03_tank_strapping, u04_alarm_ring, u05_pump_duty_records, u06_cascade_nested, x01_pump_station |
| translator | passed | 0 |  |
| translator | failed | 0 |  |
| frontend+translator | rejected | 7 | u01_sensor_voting, u02_valve_manifold, u03_tank_strapping, u04_alarm_ring, u05_pump_duty_records, u06_cascade_nested, x01_pump_station |
| frontend+translator | passed | 0 |  |
| frontend+translator | failed | 0 |  |

How to read a model's pass where the translator rejected the source: The model produced an FB equal to matiec's run of the reference on these stimuli, using the dialect's stated semantics, where the current translator's parser stops. 0 of 7 of these programs fall to a small syntax front-end, and the others need ordinary compiler work (flattening and inlining). This does not show the model can do what deterministic code cannot, that it knows vendor semantics, or that the FB matches a real S7 or Logix controller.

## Aggregate

| Model | Mode | Runs | Not run | Tuning equal | Held-out equal | Passed | Passed where translator rejected | Passed where frontend+translator did not pass | Passed and persistent | Passed, needs reading | Passed and restructured | Cost USD | Spent now USD | Cost per pass USD | Fell back | Failures |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| claude-sonnet-5-5 | llm_repair | 7 | 0 | 7 | 7 | 7 | 7 | 7 | 0 | 0 | 1 | 0.3849 | 0.3849 | 0.0550 | 0 |  |
| deterministic-translator | baseline | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | n/a | 0 | {'baseline_rejected': 7} |

## Per program, mode and repeat

| Set | Program | Translator | Frontend+translator | Mode | Model | Repeat | Tuning equal | Held-out equal | Passed | Attempts | Input tokens | Output tokens | Cost USD | ECC states | Working states | Restructured | Persistent | Control states | Has CASE | Failure |
|---|---|---|---|---|---|--:|---|---|---|--:|--:|--:|--:|--:|--:|---|---|--:|---|---|
| unsupported_st | u01_sensor_voting | rejected | rejected | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | no | baseline_rejected |
| unsupported_st | u02_valve_manifold | rejected | rejected | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | no | baseline_rejected |
| unsupported_st | u03_tank_strapping | rejected | rejected | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | no | baseline_rejected |
| unsupported_st | u04_alarm_ring | rejected | rejected | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | no | baseline_rejected |
| unsupported_st | u05_pump_duty_records | rejected | rejected | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | no | baseline_rejected |
| unsupported_st | u06_cascade_nested | rejected | rejected | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | no | baseline_rejected |
| stress | x01_pump_station | rejected | rejected | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | yes | baseline_rejected |
| unsupported_st | u01_sensor_voting | rejected | rejected | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 6861 | 2699 | 0.0436 | 2 | 1 | no | no | 1 | no |  |
| unsupported_st | u02_valve_manifold | rejected | rejected | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 7046 | 4307 | 0.0468 | 2 | 1 | no | no | 1 | no |  |
| unsupported_st | u03_tank_strapping | rejected | rejected | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 6512 | 2111 | 0.0238 | 3 | 2 | yes | no | 1 | no |  |
| unsupported_st | u04_alarm_ring | rejected | rejected | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 7051 | 4275 | 0.0465 | 2 | 1 | no | no | 1 | no |  |
| unsupported_st | u05_pump_duty_records | rejected | rejected | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 7360 | 3556 | 0.0399 | 2 | 1 | no | no | 1 | no |  |
| unsupported_st | u06_cascade_nested | rejected | rejected | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 7253 | 2329 | 0.0274 | 2 | 1 | no | no | 1 | no |  |
| stress | x01_pump_station | rejected | rejected | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 9741 | 14784 | 0.1570 | 2 | 1 | no | no | 1 | yes |  |
