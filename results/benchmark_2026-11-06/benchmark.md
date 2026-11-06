# LLM benchmark

`client`: `live`. Prices as cached on 2026-10-06; check real cost against the Console.

A run passes only if its final candidate equals matiec on the tuning stimulus and on the held-out stimulus,
which the model never saw. `restructured` is about structure only: it means at least two EC states with
actions, so `no` on a correct run is a one-state wrapper, which is what a program with no state machine should get.

In the same repeat, `llm_only` and `llm_repair` share their first attempt, because the prompt is identical and the
cache serves it. So the two modes are paired samples and not independent ones. `Cost USD` is what each mode would
have cost alone, so it counts that request in both. `Spent now USD` is what this run actually paid.

## Aggregate

| Model | Mode | Runs | Not run | Tuning equal | Held-out equal | Passed | Passed and restructured | Cost USD | Spent now USD | Cost per pass USD | Fell back | Failures |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| claude-opus-5-5 | llm_only | 21 | 0 | 21 | 21 | 21 | 3 | 1.3399 | 1.3399 | 0.0638 | 0 |  |
| claude-opus-5-5 | llm_repair | 21 | 0 | 21 | 21 | 21 | 3 | 1.3399 | 0.0000 | 0.0638 | 0 |  |
| claude-sonnet-5-5 | llm_only | 63 | 0 | 60 | 60 | 60 | 8 | 1.9741 | 1.8404 | 0.0329 | 0 | {'compile_error': 3} |
| claude-sonnet-5-5 | llm_repair | 63 | 0 | 62 | 62 | 62 | 8 | 2.1921 | 0.2180 | 0.0354 | 0 | {'compile_error': 1} |
| deterministic-translator | baseline | 21 | 0 | 21 | 21 | 21 | 0 | 0.0000 | 0.0000 | 0.0000 | 0 |  |

## Per program, mode and repeat

| Program | Mode | Model | Repeat | Tuning equal | Held-out equal | Passed | Attempts | Input tokens | Output tokens | Cost USD | ECC states | Working states | Restructured | Has CASE | Failure |
|---|---|---|--:|---|---|---|--:|--:|--:|--:|--:|--:|---|---|---|
| 00_latch | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no |  |
| 01_motor_start_stop | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no |  |
| 02_tank_hysteresis | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no |  |
| 03_scaling_clamp | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no |  |
| 04_parts_counter | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no |  |
| 05_alarm_debounce_ack | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no |  |
| 06_star_delta | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no |  |
| 07_conveyor_interlock | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no |  |
| 08_first_out_alarm | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no |  |
| 09_totalizer | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no |  |
| 10_valve_feedback | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no |  |
| 11_ramp_generator | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no |  |
| 12_pid_loop | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no |  |
| 13_case_sequencer | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | yes |  |
| 14_batch_filling | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | yes |  |
| 15_duty_standby | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no |  |
| 16_pump_station_level | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no |  |
| 17_pump_station_protection | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no |  |
| 18_pump_station_rotation | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | yes |  |
| 19_auto_restart | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | no |  |
| 20_pump_station_supervisor | baseline | deterministic-translator | 0 | yes | yes | yes | 0 | 0 | 0 | 0.0000 | 2 | 1 | no | yes |  |
| 00_latch | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5422 | 757 | 0.0091 | 2 | 1 | no | no |  |
| 00_latch | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5422 | 757 | 0.0210 | 2 | 1 | no | no |  |
| 00_latch | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5422 | 757 | 0.0091 | 2 | 1 | no | no |  |
| 00_latch | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5422 | 757 | 0.0091 | 2 | 1 | no | no |  |
| 00_latch | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5422 | 757 | 0.0210 | 2 | 1 | no | no |  |
| 00_latch | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5422 | 757 | 0.0091 | 2 | 1 | no | no |  |
| 01_motor_start_stop | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5571 | 1004 | 0.0119 | 2 | 1 | no | no |  |
| 01_motor_start_stop | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5571 | 1004 | 0.0119 | 2 | 1 | no | no |  |
| 01_motor_start_stop | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5571 | 1004 | 0.0119 | 2 | 1 | no | no |  |
| 01_motor_start_stop | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5571 | 1004 | 0.0119 | 2 | 1 | no | no |  |
| 01_motor_start_stop | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5571 | 1004 | 0.0119 | 2 | 1 | no | no |  |
| 01_motor_start_stop | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5571 | 1004 | 0.0119 | 2 | 1 | no | no |  |
| 02_tank_hysteresis | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5593 | 1038 | 0.0123 | 2 | 1 | no | no |  |
| 02_tank_hysteresis | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5593 | 1038 | 0.0123 | 2 | 1 | no | no |  |
| 02_tank_hysteresis | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5593 | 1038 | 0.0123 | 2 | 1 | no | no |  |
| 02_tank_hysteresis | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5593 | 1038 | 0.0123 | 2 | 1 | no | no |  |
| 02_tank_hysteresis | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5593 | 1038 | 0.0123 | 2 | 1 | no | no |  |
| 02_tank_hysteresis | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5593 | 1038 | 0.0123 | 2 | 1 | no | no |  |
| 03_scaling_clamp | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5714 | 1207 | 0.0142 | 2 | 1 | no | no |  |
| 03_scaling_clamp | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5714 | 1205 | 0.0142 | 2 | 1 | no | no |  |
| 03_scaling_clamp | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5714 | 1207 | 0.0142 | 2 | 1 | no | no |  |
| 03_scaling_clamp | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5714 | 1207 | 0.0142 | 2 | 1 | no | no |  |
| 03_scaling_clamp | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5714 | 1205 | 0.0142 | 2 | 1 | no | no |  |
| 03_scaling_clamp | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5714 | 1207 | 0.0142 | 2 | 1 | no | no |  |
| 04_parts_counter | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5571 | 1628 | 0.0181 | 2 | 1 | no | no |  |
| 04_parts_counter | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5571 | 1628 | 0.0181 | 2 | 1 | no | no |  |
| 04_parts_counter | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5571 | 1628 | 0.0181 | 2 | 1 | no | no |  |
| 04_parts_counter | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5571 | 1628 | 0.0181 | 2 | 1 | no | no |  |
| 04_parts_counter | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5571 | 1628 | 0.0181 | 2 | 1 | no | no |  |
| 04_parts_counter | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5571 | 1628 | 0.0181 | 2 | 1 | no | no |  |
| 05_alarm_debounce_ack | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5691 | 3036 | 0.0324 | 2 | 1 | no | no |  |
| 05_alarm_debounce_ack | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5691 | 3036 | 0.0324 | 2 | 1 | no | no |  |
| 05_alarm_debounce_ack | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5691 | 3036 | 0.0324 | 2 | 1 | no | no |  |
| 05_alarm_debounce_ack | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5691 | 3036 | 0.0324 | 2 | 1 | no | no |  |
| 05_alarm_debounce_ack | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5691 | 3036 | 0.0324 | 2 | 1 | no | no |  |
| 05_alarm_debounce_ack | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5691 | 3036 | 0.0324 | 2 | 1 | no | no |  |
| 06_star_delta | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5660 | 2739 | 0.0294 | 2 | 1 | no | no |  |
| 06_star_delta | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5660 | 2739 | 0.0294 | 2 | 1 | no | no |  |
| 06_star_delta | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5660 | 2739 | 0.0294 | 2 | 1 | no | no |  |
| 06_star_delta | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5660 | 2739 | 0.0294 | 2 | 1 | no | no |  |
| 06_star_delta | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5660 | 2739 | 0.0294 | 2 | 1 | no | no |  |
| 06_star_delta | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5660 | 2739 | 0.0294 | 2 | 1 | no | no |  |
| 07_conveyor_interlock | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5987 | 4468 | 0.0473 | 2 | 1 | no | no |  |
| 07_conveyor_interlock | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5987 | 4468 | 0.0473 | 2 | 1 | no | no |  |
| 07_conveyor_interlock | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5987 | 4468 | 0.0473 | 2 | 1 | no | no |  |
| 07_conveyor_interlock | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5987 | 4468 | 0.0473 | 2 | 1 | no | no |  |
| 07_conveyor_interlock | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5987 | 4468 | 0.0473 | 2 | 1 | no | no |  |
| 07_conveyor_interlock | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5987 | 4468 | 0.0473 | 2 | 1 | no | no |  |
| 08_first_out_alarm | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5743 | 1161 | 0.0138 | 2 | 1 | no | no |  |
| 08_first_out_alarm | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5743 | 1161 | 0.0138 | 2 | 1 | no | no |  |
| 08_first_out_alarm | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5743 | 1161 | 0.0138 | 2 | 1 | no | no |  |
| 08_first_out_alarm | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5743 | 1161 | 0.0138 | 2 | 1 | no | no |  |
| 08_first_out_alarm | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5743 | 1161 | 0.0138 | 2 | 1 | no | no |  |
| 08_first_out_alarm | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5743 | 1161 | 0.0138 | 2 | 1 | no | no |  |
| 09_totalizer | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5733 | 1246 | 0.0146 | 2 | 1 | no | no |  |
| 09_totalizer | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5733 | 1246 | 0.0146 | 2 | 1 | no | no |  |
| 09_totalizer | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5733 | 1246 | 0.0146 | 2 | 1 | no | no |  |
| 09_totalizer | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5733 | 1246 | 0.0146 | 2 | 1 | no | no |  |
| 09_totalizer | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5733 | 1246 | 0.0146 | 2 | 1 | no | no |  |
| 09_totalizer | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5733 | 1246 | 0.0146 | 2 | 1 | no | no |  |
| 10_valve_feedback | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5920 | 3127 | 0.0338 | 2 | 1 | no | no |  |
| 10_valve_feedback | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5920 | 3127 | 0.0338 | 2 | 1 | no | no |  |
| 10_valve_feedback | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5920 | 3127 | 0.0338 | 2 | 1 | no | no |  |
| 10_valve_feedback | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5920 | 3127 | 0.0338 | 2 | 1 | no | no |  |
| 10_valve_feedback | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5920 | 3127 | 0.0338 | 2 | 1 | no | no |  |
| 10_valve_feedback | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5920 | 3127 | 0.0338 | 2 | 1 | no | no |  |
| 11_ramp_generator | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5806 | 1305 | 0.0153 | 2 | 1 | no | no |  |
| 11_ramp_generator | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5806 | 1305 | 0.0153 | 2 | 1 | no | no |  |
| 11_ramp_generator | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5806 | 1305 | 0.0153 | 2 | 1 | no | no |  |
| 11_ramp_generator | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5806 | 1305 | 0.0153 | 2 | 1 | no | no |  |
| 11_ramp_generator | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5806 | 1305 | 0.0153 | 2 | 1 | no | no |  |
| 11_ramp_generator | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5806 | 1305 | 0.0153 | 2 | 1 | no | no |  |
| 12_pid_loop | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5966 | 1610 | 0.0187 | 2 | 1 | no | no |  |
| 12_pid_loop | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5966 | 1610 | 0.0187 | 2 | 1 | no | no |  |
| 12_pid_loop | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5966 | 1610 | 0.0187 | 2 | 1 | no | no |  |
| 12_pid_loop | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5966 | 1610 | 0.0187 | 2 | 1 | no | no |  |
| 12_pid_loop | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5966 | 1610 | 0.0187 | 2 | 1 | no | no |  |
| 12_pid_loop | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5966 | 1610 | 0.0187 | 2 | 1 | no | no |  |
| 13_case_sequencer | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 6087 | 3858 | 0.0414 | 10 | 9 | yes | yes |  |
| 13_case_sequencer | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 6087 | 3858 | 0.0414 | 10 | 9 | yes | yes |  |
| 13_case_sequencer | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 6087 | 3858 | 0.0414 | 10 | 9 | yes | yes |  |
| 13_case_sequencer | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 6087 | 3858 | 0.0414 | 10 | 9 | yes | yes |  |
| 13_case_sequencer | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 6087 | 3858 | 0.0414 | 10 | 9 | yes | yes |  |
| 13_case_sequencer | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 6087 | 3858 | 0.0414 | 10 | 9 | yes | yes |  |
| 14_batch_filling | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 6349 | 5334 | 0.0567 | 8 | 7 | yes | yes |  |
| 14_batch_filling | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 6349 | 5478 | 0.0582 | 9 | 7 | yes | yes |  |
| 14_batch_filling | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 6349 | 5461 | 0.0580 | 9 | 7 | yes | yes |  |
| 14_batch_filling | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 6349 | 5334 | 0.0567 | 8 | 7 | yes | yes |  |
| 14_batch_filling | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 6349 | 5478 | 0.0582 | 9 | 7 | yes | yes |  |
| 14_batch_filling | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 6349 | 5461 | 0.0580 | 9 | 7 | yes | yes |  |
| 15_duty_standby | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5989 | 3366 | 0.0363 | 2 | 1 | no | no |  |
| 15_duty_standby | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5989 | 3613 | 0.0388 | 2 | 1 | no | no |  |
| 15_duty_standby | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5989 | 3613 | 0.0388 | 2 | 1 | no | no |  |
| 15_duty_standby | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5989 | 3366 | 0.0363 | 2 | 1 | no | no |  |
| 15_duty_standby | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5989 | 3613 | 0.0388 | 2 | 1 | no | no |  |
| 15_duty_standby | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5989 | 3613 | 0.0388 | 2 | 1 | no | no |  |
| 16_pump_station_level | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 6137 | 3478 | 0.0377 | 2 | 1 | no | no |  |
| 16_pump_station_level | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 6137 | 3478 | 0.0377 | 2 | 1 | no | no |  |
| 16_pump_station_level | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 6137 | 3478 | 0.0377 | 2 | 1 | no | no |  |
| 16_pump_station_level | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 6137 | 3478 | 0.0377 | 2 | 1 | no | no |  |
| 16_pump_station_level | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 6137 | 3478 | 0.0377 | 2 | 1 | no | no |  |
| 16_pump_station_level | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 6137 | 3478 | 0.0377 | 2 | 1 | no | no |  |
| 17_pump_station_protection | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 6135 | 4981 | 0.0528 | 2 | 1 | no | no |  |
| 17_pump_station_protection | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 6135 | 4983 | 0.0528 | 2 | 1 | no | no |  |
| 17_pump_station_protection | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 6135 | 4981 | 0.0528 | 2 | 1 | no | no |  |
| 17_pump_station_protection | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 6135 | 4981 | 0.0528 | 2 | 1 | no | no |  |
| 17_pump_station_protection | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 6135 | 4983 | 0.0528 | 2 | 1 | no | no |  |
| 17_pump_station_protection | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 6135 | 4981 | 0.0528 | 2 | 1 | no | no |  |
| 18_pump_station_rotation | llm_only | claude-sonnet-5-5 | 0 | no | n/a | no | 1 | 6580 | 3160 | 0.0354 | 2 | 1 | no | yes | compile_error |
| 18_pump_station_rotation | llm_only | claude-sonnet-5-5 | 1 | no | n/a | no | 1 | 6580 | 3160 | 0.0354 | 2 | 1 | no | yes | compile_error |
| 18_pump_station_rotation | llm_only | claude-sonnet-5-5 | 2 | no | n/a | no | 1 | 6580 | 3160 | 0.0354 | 2 | 1 | no | yes | compile_error |
| 18_pump_station_rotation | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 2 | 16408 | 6517 | 0.0794 | 2 | 1 | no | yes |  |
| 18_pump_station_rotation | llm_repair | claude-sonnet-5-5 | 1 | no | n/a | no | 3 | 26236 | 9480 | 0.1193 | 2 | 1 | no | yes | compile_error |
| 18_pump_station_rotation | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 3 | 26236 | 10108 | 0.1256 | 2 | 1 | no | yes |  |
| 19_auto_restart | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5990 | 4069 | 0.0434 | 2 | 1 | no | no |  |
| 19_auto_restart | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5990 | 4069 | 0.0434 | 2 | 1 | no | no |  |
| 19_auto_restart | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5990 | 4069 | 0.0434 | 2 | 1 | no | no |  |
| 19_auto_restart | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 5990 | 4069 | 0.0434 | 2 | 1 | no | no |  |
| 19_auto_restart | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 5990 | 4069 | 0.0434 | 2 | 1 | no | no |  |
| 19_auto_restart | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 5990 | 4069 | 0.0434 | 2 | 1 | no | no |  |
| 20_pump_station_supervisor | llm_only | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 7561 | 7735 | 0.0832 | 10 | 9 | yes | yes |  |
| 20_pump_station_supervisor | llm_only | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 7561 | 5555 | 0.0614 | 2 | 1 | no | yes |  |
| 20_pump_station_supervisor | llm_only | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 7561 | 7999 | 0.0858 | 10 | 9 | yes | yes |  |
| 20_pump_station_supervisor | llm_repair | claude-sonnet-5-5 | 0 | yes | yes | yes | 1 | 7561 | 7735 | 0.0832 | 10 | 9 | yes | yes |  |
| 20_pump_station_supervisor | llm_repair | claude-sonnet-5-5 | 1 | yes | yes | yes | 1 | 7561 | 5555 | 0.0614 | 2 | 1 | no | yes |  |
| 20_pump_station_supervisor | llm_repair | claude-sonnet-5-5 | 2 | yes | yes | yes | 1 | 7561 | 7999 | 0.0858 | 10 | 9 | yes | yes |  |
| 00_latch | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5422 | 746 | 0.0418 | 2 | 1 | no | no |  |
| 00_latch | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5422 | 746 | 0.0418 | 2 | 1 | no | no |  |
| 01_motor_start_stop | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5571 | 993 | 0.0225 | 2 | 1 | no | no |  |
| 01_motor_start_stop | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5571 | 993 | 0.0225 | 2 | 1 | no | no |  |
| 02_tank_hysteresis | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5593 | 1038 | 0.0235 | 2 | 1 | no | no |  |
| 02_tank_hysteresis | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5593 | 1038 | 0.0235 | 2 | 1 | no | no |  |
| 03_scaling_clamp | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5714 | 1205 | 0.0273 | 2 | 1 | no | no |  |
| 03_scaling_clamp | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5714 | 1205 | 0.0273 | 2 | 1 | no | no |  |
| 04_parts_counter | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5571 | 1851 | 0.0396 | 2 | 1 | no | no |  |
| 04_parts_counter | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5571 | 1851 | 0.0396 | 2 | 1 | no | no |  |
| 05_alarm_debounce_ack | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5691 | 2904 | 0.0612 | 2 | 1 | no | no |  |
| 05_alarm_debounce_ack | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5691 | 2904 | 0.0612 | 2 | 1 | no | no |  |
| 06_star_delta | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5660 | 2662 | 0.0562 | 2 | 1 | no | no |  |
| 06_star_delta | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5660 | 2662 | 0.0562 | 2 | 1 | no | no |  |
| 07_conveyor_interlock | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5987 | 4131 | 0.0869 | 2 | 1 | no | no |  |
| 07_conveyor_interlock | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5987 | 4131 | 0.0869 | 2 | 1 | no | no |  |
| 08_first_out_alarm | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5743 | 1161 | 0.0265 | 2 | 1 | no | no |  |
| 08_first_out_alarm | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5743 | 1161 | 0.0265 | 2 | 1 | no | no |  |
| 09_totalizer | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5733 | 1410 | 0.0315 | 2 | 1 | no | no |  |
| 09_totalizer | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5733 | 1410 | 0.0315 | 2 | 1 | no | no |  |
| 10_valve_feedback | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5920 | 2979 | 0.0636 | 2 | 1 | no | no |  |
| 10_valve_feedback | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5920 | 2979 | 0.0636 | 2 | 1 | no | no |  |
| 11_ramp_generator | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5806 | 1305 | 0.0297 | 2 | 1 | no | no |  |
| 11_ramp_generator | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5806 | 1305 | 0.0297 | 2 | 1 | no | no |  |
| 12_pid_loop | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5966 | 1613 | 0.0365 | 2 | 1 | no | no |  |
| 12_pid_loop | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5966 | 1613 | 0.0365 | 2 | 1 | no | no |  |
| 13_case_sequencer | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 6087 | 4167 | 0.0880 | 10 | 9 | yes | yes |  |
| 13_case_sequencer | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 6087 | 4167 | 0.0880 | 10 | 9 | yes | yes |  |
| 14_batch_filling | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 6349 | 5083 | 0.1074 | 9 | 7 | yes | yes |  |
| 14_batch_filling | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 6349 | 5083 | 0.1074 | 9 | 7 | yes | yes |  |
| 15_duty_standby | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5989 | 3697 | 0.0782 | 2 | 1 | no | no |  |
| 15_duty_standby | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5989 | 3697 | 0.0782 | 2 | 1 | no | no |  |
| 16_pump_station_level | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 6137 | 3739 | 0.0797 | 2 | 1 | no | no |  |
| 16_pump_station_level | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 6137 | 3739 | 0.0797 | 2 | 1 | no | no |  |
| 17_pump_station_protection | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 6135 | 5286 | 0.1106 | 2 | 1 | no | no |  |
| 17_pump_station_protection | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 6135 | 5286 | 0.1106 | 2 | 1 | no | no |  |
| 18_pump_station_rotation | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 6580 | 3487 | 0.0764 | 2 | 1 | no | yes |  |
| 18_pump_station_rotation | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 6580 | 3487 | 0.0764 | 2 | 1 | no | yes |  |
| 19_auto_restart | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5990 | 4415 | 0.0926 | 2 | 1 | no | no |  |
| 19_auto_restart | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 5990 | 4415 | 0.0926 | 2 | 1 | no | no |  |
| 20_pump_station_supervisor | llm_only | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 7561 | 7483 | 0.1602 | 10 | 9 | yes | yes |  |
| 20_pump_station_supervisor | llm_repair | claude-opus-5-5 | 0 | yes | yes | yes | 1 | 7561 | 7483 | 0.1602 | 10 | 9 | yes | yes |  |
