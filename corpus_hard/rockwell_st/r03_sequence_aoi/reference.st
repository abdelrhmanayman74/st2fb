(* Hand-written reference for program.l5k. Used only as the matiec oracle, and never shown to a model. *)
FUNCTION_BLOCK CipSequence_AOI
VAR_INPUT
  StartCmd : BOOL;
  HoldCmd : BOOL;
  AbortCmd : BOOL;
  ConductivityOk : BOOL;
  RinseMs : DINT;
  WashMs : DINT;
  TaskPeriodMs : DINT;
END_VAR
VAR_OUTPUT
  StepNo : DINT;
  WaterValve : BOOL;
  CausticValve : BOOL;
  ReturnPump : BOOL;
  StepRemainingMs : DINT;
  DeviationAlarm : BOOL;
  CycleCount : DINT;
END_VAR
VAR
  Step_EN, Step_TT, Step_DN, Step_PREV : BOOL;
  Step_ACC : DINT;
  Dev_EN, Dev_TT, Dev_DN, Dev_PREV : BOOL;
  Dev_ACC : DINT;
  StartOneShot : R_TRIG;
  Preset : DINT;
END_VAR
  StartOneShot(CLK := StartCmd);

  WaterValve := FALSE;
  CausticValve := FALSE;
  ReturnPump := FALSE;

  IF AbortCmd THEN
    StepNo := 0;
    Step_ACC := 0;
    Step_DN := FALSE;
    Step_EN := FALSE;
    Step_TT := FALSE;
    Step_PREV := FALSE;
  END_IF;

  CASE StepNo OF
    0:
      Preset := RinseMs;
      IF StartOneShot.Q AND NOT AbortCmd THEN
        StepNo := 10;
      END_IF;
    10:
      WaterValve := TRUE;
      ReturnPump := TRUE;
      IF Step_DN THEN
        Step_ACC := 0;
        Step_DN := FALSE;
        Step_EN := FALSE;
        Step_TT := FALSE;
        Step_PREV := FALSE;
        Preset := WashMs;
        StepNo := 20;
      END_IF;
    20:
      CausticValve := TRUE;
      ReturnPump := TRUE;
      IF Step_DN THEN
        Step_ACC := 0;
        Step_DN := FALSE;
        Step_EN := FALSE;
        Step_TT := FALSE;
        Step_PREV := FALSE;
        Preset := RinseMs;
        StepNo := 30;
      END_IF;
    30:
      WaterValve := TRUE;
      ReturnPump := TRUE;
      IF Step_DN THEN
        Step_ACC := 0;
        Step_DN := FALSE;
        Step_EN := FALSE;
        Step_TT := FALSE;
        Step_PREV := FALSE;
        CycleCount := CycleCount + 1;
        StepNo := 0;
      END_IF;
  END_CASE;

  Step_EN := ((StepNo = 10) OR (StepNo = 30) OR ((StepNo = 20) AND ConductivityOk)) AND NOT HoldCmd;
  IF Step_EN THEN
    IF Step_PREV AND NOT Step_DN THEN
      Step_ACC := Step_ACC + TaskPeriodMs;
      IF Step_ACC >= Preset THEN
        Step_ACC := Preset;
        Step_DN := TRUE;
      END_IF;
    END_IF;
  ELSE
    Step_ACC := 0;
    Step_DN := FALSE;
  END_IF;
  Step_TT := Step_EN AND NOT Step_DN;
  Step_PREV := Step_EN;
  StepRemainingMs := Preset - Step_ACC;

  Dev_EN := (StepNo = 20) AND NOT ConductivityOk;
  IF Dev_EN THEN
    IF Dev_PREV AND NOT Dev_DN THEN
      Dev_ACC := Dev_ACC + TaskPeriodMs;
      IF Dev_ACC >= 200 THEN
        Dev_ACC := 200;
        Dev_DN := TRUE;
      END_IF;
    END_IF;
  ELSE
    Dev_ACC := 0;
    Dev_DN := FALSE;
  END_IF;
  Dev_TT := Dev_EN AND NOT Dev_DN;
  Dev_PREV := Dev_EN;
  DeviationAlarm := Dev_DN;
END_FUNCTION_BLOCK
