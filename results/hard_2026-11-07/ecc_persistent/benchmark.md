# LLM benchmark, hard corpus

`client`: `live`. Sets: corpus. Requested form: ecc_persistent. Prices as cached on 2026-10-06; check real cost against the Console.

A run passes only if its final candidate equals matiec on the tuning stimulus and on the held-out stimulus. Structure never decides a pass.
`Persistent` is the strict metric: control position is held by ECC state across REQ events. See `st2fb/llm/ecc_metric.py`. `Restructured` only counts states with actions.

These programs were written by this project, except public_st. SCL and Logix sources were never compiled by TIA Portal or Studio 5000, and the oracle for them is a hand-written
translation, so an error in the pairing would count against the model. Inspect a failure before assuming that the model is wrong. See `docs/HARD_CORPUS.md`.


## Baseline tiers

Two deterministic comparators run on every program. `translator` is the current translator on what the model sees. `frontend+translator` puts `st2fb/vendor_frontend.py`, a small syntax rewrite
that never sees the reference, in front of it. `rejected` under `translator` means only that this parser or scope stopped, and it is the expected result here. A model's pass is compared with both tiers.

| Tier | Status | Programs | Which |
|---|---|--:|---|
| translator | rejected | 0 |  |
| translator | passed | 4 | 06_star_delta, 13_case_sequencer, 14_batch_filling, 20_pump_station_supervisor |
| translator | failed | 0 |  |
| frontend+translator | rejected | 0 |  |
| frontend+translator | passed | 4 | 06_star_delta, 13_case_sequencer, 14_batch_filling, 20_pump_station_supervisor |
| frontend+translator | failed | 0 |  |

How to read a model's pass where the translator rejected the source: The model produced an FB equal to matiec's run of the reference on these stimuli, using the dialect's stated semantics, where the current translator's parser stops. 0 of 0 of these programs fall to a small syntax front-end, and the others need ordinary compiler work (flattening and inlining). This does not show the model can do what deterministic code cannot, that it knows vendor semantics, or that the FB matches a real S7 or Logix controller.

## Aggregate

| Model | Mode | Runs | Not run | Tuning equal | Held-out equal | Passed | Passed where translator rejected | Passed where frontend+translator did not pass | Passed and persistent | Passed, needs reading | Passed and restructured | Cost USD | Spent now USD | Cost per pass USD | Fell back | Failures |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| claude-sonnet-5-5 | llm_repair | 4 | 0 | 4 | 4 | 4 | 0 | 0 | 3 | 0 | 4 | 0.4283 | 0.4283 | 0.1071 | 0 |  |
| deterministic-translator | baseline | 4 | 0 | 4 | 4 | 4 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | 0.0000 | 0 |  |

## Per program, mode and repeat

| Set | Program | Translator | Frontend+translator | Mode | Model | Repeat | Tuning equal | Held-out equal | Passed | Attempts | Input tokens | Output tokens | Cost USD | ECC states | Working states | Restructured | Persistent | Control states | Has CASE | Failure |
|---|---|---|---|---|---|--:|---|---|---|--:|--:|--:|--:|--:|--:|---|---|--:|---|---|
|  | 06_star_delta | passed | passed | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no | 1 | no |  |
|  | 13_case_sequencer | passed | passed | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no | 1 | yes |  |
|  | 14_batch_filling | passed | passed | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no | 1 | yes |  |
|  | 20_pump_station_supervisor | passed | passed | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no | 1 | yes |  |
|  | 06_star_delta | passed | passed | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 7484 | 4327 | 0.0617 | 4 | 2 | yes | no | 2 | no |  |
|  | 13_case_sequencer | passed | passed | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 7911 | 7788 | 0.0811 | 19 | 10 | yes | yes | 9 | yes |  |
|  | 14_batch_filling | passed | passed | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 2 | 22457 | 15769 | 0.1774 | 11 | 6 | yes | yes | 5 | yes |  |
|  | 20_pump_station_supervisor | passed | passed | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 9385 | 10189 | 0.1081 | 12 | 6 | yes | yes | 6 | yes |  |
