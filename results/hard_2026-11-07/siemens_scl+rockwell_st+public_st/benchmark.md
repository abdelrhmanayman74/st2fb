# LLM benchmark, hard corpus

`client`: `live`. Sets: siemens_scl, rockwell_st, public_st. Requested form: default. Prices as cached on 2026-10-06; check real cost against the Console.

A run passes only if its final candidate equals matiec on the tuning stimulus and on the held-out stimulus. Structure never decides a pass.
`Persistent` is the strict metric: control position is held by ECC state across REQ events. See `st2fb/llm/ecc_metric.py`. `Restructured` only counts states with actions.

These programs were written by this project, except public_st. SCL and Logix sources were never compiled by TIA Portal or Studio 5000, and the oracle for them is a hand-written
translation, so an error in the pairing would count against the model. Inspect a failure before assuming that the model is wrong. See `docs/HARD_CORPUS.md`.

- `siemens_scl`: TIA-style, never compiled, judged by matiec readings.
- `rockwell_st`: Logix-flavoured dialect with invented instructions.
- `public_st`: public programs; p03 and p04 pass the translator, so they say nothing about model against baseline.

## Baseline tiers

Two deterministic comparators run on every program. `translator` is the current translator on what the model sees. `frontend+translator` puts `st2fb/vendor_frontend.py`, a small syntax rewrite
that never sees the reference, in front of it. `rejected` under `translator` means only that this parser or scope stopped, and it is the expected result here. A model's pass is compared with both tiers.

| Tier | Status | Programs | Which |
|---|---|--:|---|
| translator | rejected | 14 | s01_conveyor_starter, s02_analog_input, s03_valve_monitor, s04_batch_steps, s05_lead_lag_array, s06_status_word, s07_heater_pi, s08_packaging_counter, r01_motor_aoi, r02_fill_retry_aoi, r03_sequence_aoi, r04_alarm_word_aoi, p01_bistable_device, p02_pi_controller |
| translator | passed | 2 | p03_alpha_beta_filter, p04_debounce_bool |
| translator | failed | 0 |  |
| frontend+translator | rejected | 2 | s05_lead_lag_array, p02_pi_controller |
| frontend+translator | passed | 14 | s01_conveyor_starter, s02_analog_input, s03_valve_monitor, s04_batch_steps, s06_status_word, s07_heater_pi, s08_packaging_counter, r01_motor_aoi, r02_fill_retry_aoi, r03_sequence_aoi, r04_alarm_word_aoi, p01_bistable_device, p03_alpha_beta_filter, p04_debounce_bool |
| frontend+translator | failed | 0 |  |

How to read a model's pass where the translator rejected the source: The model produced an FB equal to matiec's run of the reference on these stimuli, using the dialect's stated semantics, where the current translator's parser stops. 12 of 14 of these programs fall to a small syntax front-end, and the others need ordinary compiler work (flattening and inlining). This does not show the model can do what deterministic code cannot, that it knows vendor semantics, or that the FB matches a real S7 or Logix controller.

## Aggregate

| Model | Mode | Runs | Not run | Tuning equal | Held-out equal | Passed | Passed where translator rejected | Passed where frontend+translator did not pass | Passed and persistent | Passed, needs reading | Passed and restructured | Cost USD | Spent now USD | Cost per pass USD | Fell back | Failures |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| claude-sonnet-5-5 | llm_repair | 16 | 0 | 16 | 16 | 16 | 14 | 2 | 0 | 0 | 0 | 0.5725 | 0.5725 | 0.0358 | 0 |  |
| deterministic-translator | baseline | 16 | 0 | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | 0.0000 | 0 | {'baseline_rejected': 14} |

## Per program, mode and repeat

| Set | Program | Translator | Frontend+translator | Mode | Model | Repeat | Tuning equal | Held-out equal | Passed | Attempts | Input tokens | Output tokens | Cost USD | ECC states | Working states | Restructured | Persistent | Control states | Has CASE | Failure |
|---|---|---|---|---|---|--:|---|---|---|--:|--:|--:|--:|--:|--:|---|---|--:|---|---|
| siemens_scl | s01_conveyor_starter | rejected | passed | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | no | baseline_rejected |
| siemens_scl | s02_analog_input | rejected | passed | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | no | baseline_rejected |
| siemens_scl | s03_valve_monitor | rejected | passed | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | no | baseline_rejected |
| siemens_scl | s04_batch_steps | rejected | passed | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | yes | baseline_rejected |
| siemens_scl | s05_lead_lag_array | rejected | rejected | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | no | baseline_rejected |
| siemens_scl | s06_status_word | rejected | passed | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | no | baseline_rejected |
| siemens_scl | s07_heater_pi | rejected | passed | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | no | baseline_rejected |
| siemens_scl | s08_packaging_counter | rejected | passed | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | no | baseline_rejected |
| rockwell_st | r01_motor_aoi | rejected | passed | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | no | baseline_rejected |
| rockwell_st | r02_fill_retry_aoi | rejected | passed | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | no | baseline_rejected |
| rockwell_st | r03_sequence_aoi | rejected | passed | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | yes | baseline_rejected |
| rockwell_st | r04_alarm_word_aoi | rejected | passed | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | no | baseline_rejected |
| public_st | p01_bistable_device | rejected | passed | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | yes | baseline_rejected |
| public_st | p02_pi_controller | rejected | rejected | baseline | deterministic-translator | 0 | n/a | n/a | no | 0 | 0 | 0 | 0.0000 | n/a | n/a | n/a | n/a | n/a | no | baseline_rejected |
| public_st | p03_alpha_beta_filter | passed | passed | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no | 1 | no |  |
| public_st | p04_debounce_bool | passed | passed | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no | 1 | no |  |
| siemens_scl | s01_conveyor_starter | rejected | passed | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 8057 | 3068 | 0.0501 | 2 | 1 | no | no | 1 | no |  |
| siemens_scl | s02_analog_input | rejected | passed | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 8140 | 3565 | 0.0399 | 2 | 1 | no | no | 1 | no |  |
| siemens_scl | s03_valve_monitor | rejected | passed | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 7901 | 3059 | 0.0344 | 2 | 1 | no | no | 1 | no |  |
| siemens_scl | s04_batch_steps | rejected | passed | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 8292 | 3499 | 0.0395 | 2 | 1 | no | no | 1 | yes |  |
| siemens_scl | s05_lead_lag_array | rejected | rejected | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 8041 | 2160 | 0.0256 | 2 | 1 | no | no | 1 | no |  |
| siemens_scl | s06_status_word | rejected | passed | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 7897 | 1815 | 0.0219 | 2 | 1 | no | no | 1 | no |  |
| siemens_scl | s07_heater_pi | rejected | passed | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 7650 | 1498 | 0.0182 | 2 | 1 | no | no | 1 | no |  |
| siemens_scl | s08_packaging_counter | rejected | passed | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 8130 | 3301 | 0.0372 | 2 | 1 | no | no | 1 | no |  |
| rockwell_st | r01_motor_aoi | rejected | passed | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 7706 | 2470 | 0.0435 | 2 | 1 | no | no | 1 | no |  |
| rockwell_st | r02_fill_retry_aoi | rejected | passed | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 7928 | 3649 | 0.0403 | 2 | 1 | no | no | 1 | no |  |
| rockwell_st | r03_sequence_aoi | rejected | passed | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 2 | 19126 | 6509 | 0.0793 | 2 | 1 | no | no | 1 | yes |  |
| rockwell_st | r04_alarm_word_aoi | rejected | passed | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 7965 | 2896 | 0.0329 | 2 | 1 | no | no | 1 | no |  |
| public_st | p01_bistable_device | rejected | passed | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 6502 | 3244 | 0.0483 | 2 | 1 | no | no | 1 | yes |  |
| public_st | p02_pi_controller | rejected | rejected | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 7335 | 1808 | 0.0224 | 2 | 1 | no | no | 1 | no |  |
| public_st | p03_alpha_beta_filter | passed | passed | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 6481 | 1139 | 0.0140 | 2 | 1 | no | no | 1 | no |  |
| public_st | p04_debounce_bool | passed | passed | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 6263 | 2280 | 0.0250 | 2 | 1 | no | no | 1 | no |  |
