(* Hand-written reference for program.scl. Used only as the matiec oracle, and never shown to a model.
   NORM_X and SCALE_X are written out as Siemens documents them: NORM_X = (VALUE - MIN) / (MAX - MIN) and
   SCALE_X = VALUE * (MAX - MIN) + MIN. *)
FUNCTION_BLOCK FB_AnalogInput
VAR_INPUT
  i_raw : INT;
  i_scaleMin : REAL;
  i_scaleMax : REAL;
  i_highLimit : REAL;
  i_lowLimit : REAL;
  i_alarmDelay : TIME;
  i_simulate : BOOL;
  i_simValue : REAL;
END_VAR
VAR_OUTPUT
  o_value : REAL;
  o_percent : INT;
  o_wireBreak : BOOL;
  o_highAlarm : BOOL;
  o_lowAlarm : BOOL;
END_VAR
VAR
  statHighTimer : TON;
  statLowTimer : TON;
  statBreakTimer : TON;
  statLastGood : REAL;
  statDelay : TIME;
  statTiming : BOOL;
  tempBreak : BOOL;
  tempHigh : BOOL;
  tempLow : BOOL;
  tempNorm : REAL;
  tempScaled : REAL;
END_VAR
  tempNorm := (INT_TO_REAL(i_raw) - 0.0) / (27648.0 - 0.0);
  tempScaled := tempNorm * (i_scaleMax - i_scaleMin) + i_scaleMin;

  IF NOT statTiming THEN
    statDelay := i_alarmDelay;
  END_IF;

  tempBreak := i_raw = 32767;
  statBreakTimer(IN := tempBreak, PT := statDelay);
  o_wireBreak := statBreakTimer.Q;
  IF i_raw <> 32767 THEN
    statLastGood := tempScaled;
  END_IF;

  IF i_simulate THEN
    o_value := i_simValue;
  ELSE
    o_value := statLastGood;
  END_IF;
  o_percent := REAL_TO_INT(100.0 * LIMIT(0.0, tempNorm, 1.0));

  tempHigh := o_value > i_highLimit;
  tempLow := o_value < i_lowLimit;
  statHighTimer(IN := tempHigh, PT := statDelay, Q => o_highAlarm);
  statLowTimer(IN := tempLow, PT := statDelay, Q => o_lowAlarm);
  statTiming := tempBreak OR tempHigh OR tempLow;
END_FUNCTION_BLOCK
