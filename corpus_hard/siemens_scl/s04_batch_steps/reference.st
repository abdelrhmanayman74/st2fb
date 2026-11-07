(* Hand-written reference for program.scl. Used only as the matiec oracle, and never shown to a model. *)
FUNCTION_BLOCK FB_BatchSteps
VAR_INPUT
  i_start : BOOL;
  i_abort : BOOL;
  i_doseDone : BOOL;
  i_tempReached : BOOL;
  i_tankEmpty : BOOL;
  i_mixTime : TIME;
  i_holdTime : TIME;
END_VAR
VAR_OUTPUT
  o_step : INT;
  o_doseValve : BOOL;
  o_mixer : BOOL;
  o_heater : BOOL;
  o_drainValve : BOOL;
  o_batches : INT;
  o_stepElapsed : TIME;
END_VAR
VAR
  statStepTimer : TON;
  statBatchCounter : CTU;
  statStartEdge : R_TRIG;
  statStepTimerRun : BOOL;
  statBatchDone : BOOL;
  statStepPreset : TIME;
END_VAR
  statStartEdge(CLK := i_start);
  statStepTimer(IN := statStepTimerRun, PT := statStepPreset, ET => o_stepElapsed);
  o_doseValve := FALSE;
  o_mixer := FALSE;
  o_heater := FALSE;
  o_drainValve := FALSE;
  statBatchDone := FALSE;
  IF i_abort AND o_step <> 0 THEN
    o_step := 90;
    statStepTimerRun := FALSE;
  END_IF;

  CASE o_step OF
    0:
      IF statStartEdge.Q AND NOT i_abort THEN
        o_step := 10;
      END_IF;
    10:
      o_doseValve := TRUE;
      IF i_doseDone THEN
        o_step := 20;
        statStepPreset := i_mixTime;
        statStepTimerRun := TRUE;
      END_IF;
    20:
      o_mixer := TRUE;
      IF statStepTimer.Q THEN
        statStepTimerRun := FALSE;
        o_step := 30;
      END_IF;
    30:
      o_mixer := TRUE;
      o_heater := TRUE;
      IF i_tempReached THEN
        o_step := 40;
        statStepPreset := i_holdTime;
        statStepTimerRun := TRUE;
      END_IF;
    40:
      o_mixer := TRUE;
      o_heater := NOT i_tempReached;
      IF statStepTimer.Q THEN
        statStepTimerRun := FALSE;
        o_step := 50;
      END_IF;
    50:
      o_drainValve := TRUE;
      IF i_tankEmpty THEN
        statBatchDone := TRUE;
        o_step := 0;
      END_IF;
    90:
      o_drainValve := TRUE;
      IF i_tankEmpty AND NOT i_abort THEN
        o_step := 0;
      END_IF;
  ELSE
    o_step := 0;
  END_CASE;

  statBatchCounter(CU := statBatchDone, R := FALSE, PV := 500, CV => o_batches);
END_FUNCTION_BLOCK
