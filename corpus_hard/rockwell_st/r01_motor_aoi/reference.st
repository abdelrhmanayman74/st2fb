(* Hand-written reference for program.l5k. Used only as the matiec oracle, and never shown to a model. Each timer is its
   members as variables plus the rules in docs/HARD_CORPUS.md: the first enabled scan leaves ACC alone, later ones add the
   task period, DN sets at PRE and stays set, and disabling clears ACC and DN. *)
FUNCTION_BLOCK MotorControl_AOI
VAR_INPUT
  StartPB : BOOL;
  StopPB : BOOL;
  Overload : BOOL;
  RunFeedback : BOOL;
  FaultReset : BOOL;
  StartDelayMs : DINT;
  FeedbackTimeoutMs : DINT;
  TaskPeriodMs : DINT;
END_VAR
VAR_OUTPUT
  RunCmd : BOOL;
  Starting : BOOL;
  Faulted : BOOL;
  DelayEnabled : BOOL;
  DelayElapsedMs : DINT;
END_VAR
VAR
  Delay_EN, Delay_TT, Delay_DN, Delay_PREV : BOOL;
  Delay_ACC : DINT;
  Fb_EN, Fb_TT, Fb_DN, Fb_PREV : BOOL;
  Fb_ACC : DINT;
  StartOneShot : R_TRIG;
  RunLatch : BOOL;
  FaultLatch : BOOL;
END_VAR
  StartOneShot(CLK := StartPB);

  IF StopPB OR Overload OR FaultLatch THEN
    RunLatch := FALSE;
  ELSIF StartOneShot.Q THEN
    RunLatch := TRUE;
  END_IF;

  Delay_EN := RunLatch;
  IF Delay_EN THEN
    IF Delay_PREV AND NOT Delay_DN THEN
      Delay_ACC := Delay_ACC + TaskPeriodMs;
      IF Delay_ACC >= StartDelayMs THEN
        Delay_ACC := StartDelayMs;
        Delay_DN := TRUE;
      END_IF;
    END_IF;
  ELSE
    Delay_ACC := 0;
    Delay_DN := FALSE;
  END_IF;
  Delay_TT := Delay_EN AND NOT Delay_DN;
  Delay_PREV := Delay_EN;
  Starting := Delay_TT;
  RunCmd := Delay_DN;
  DelayEnabled := Delay_EN;
  DelayElapsedMs := Delay_ACC;

  Fb_EN := RunCmd AND NOT RunFeedback;
  IF Fb_EN THEN
    IF Fb_PREV AND NOT Fb_DN THEN
      Fb_ACC := Fb_ACC + TaskPeriodMs;
      IF Fb_ACC >= FeedbackTimeoutMs THEN
        Fb_ACC := FeedbackTimeoutMs;
        Fb_DN := TRUE;
      END_IF;
    END_IF;
  ELSE
    Fb_ACC := 0;
    Fb_DN := FALSE;
  END_IF;
  Fb_TT := Fb_EN AND NOT Fb_DN;
  Fb_PREV := Fb_EN;

  IF Fb_DN OR Overload THEN
    FaultLatch := TRUE;
  END_IF;
  IF FaultReset AND NOT Overload THEN
    FaultLatch := FALSE;
    Fb_ACC := 0;
    Fb_DN := FALSE;
    Fb_EN := FALSE;
    Fb_TT := FALSE;
    Fb_PREV := FALSE;
  END_IF;
  Faulted := FaultLatch;
END_FUNCTION_BLOCK
