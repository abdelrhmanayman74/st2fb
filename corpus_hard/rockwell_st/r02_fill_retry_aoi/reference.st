(* Hand-written reference for program.l5k. Used only as the matiec oracle, and never shown to a model. A counter
   adds one on each rising edge of CUEnable, without stopping at PRE, and DN is ACC >= PRE. *)
FUNCTION_BLOCK FillRetry_AOI
VAR_INPUT
  FillRequest : BOOL;
  LevelPct : REAL;
  StartPct : REAL;
  StopPct : REAL;
  ValveOpen : BOOL;
  InflowPerSec : REAL;
  OpenTimeoutMs : DINT;
  RetryWaitMs : DINT;
  MaxRetries : DINT;
  Acknowledge : BOOL;
  TaskPeriodMs : DINT;
END_VAR
VAR_OUTPUT
  ValveCmd : BOOL;
  WaitingRetry : BOOL;
  LockedOut : BOOL;
  RetryCount : DINT;
  Totalised : REAL;
END_VAR
VAR
  Demand : BOOL;
  WaitActive : BOOL;
  Open_EN, Open_TT, Open_DN, Open_PREV : BOOL;
  Open_ACC : DINT;
  Wait_EN, Wait_TT, Wait_DN, Wait_PREV : BOOL;
  Wait_ACC : DINT;
  Retries_ACC : DINT;
  Retries_DN, Retries_PREV, Retries_CU : BOOL;
  AckOneShot : R_TRIG;
END_VAR
  IF LevelPct <= StartPct THEN
    Demand := TRUE;
  ELSIF LevelPct >= StopPct THEN
    Demand := FALSE;
  END_IF;

  Retries_CU := Open_DN;
  IF Retries_CU AND NOT Retries_PREV THEN
    Retries_ACC := Retries_ACC + 1;
  END_IF;
  Retries_DN := Retries_ACC >= MaxRetries;
  Retries_PREV := Retries_CU;
  RetryCount := Retries_ACC;
  LockedOut := Retries_DN;

  IF Open_DN AND NOT LockedOut THEN
    WaitActive := TRUE;
  END_IF;
  Wait_EN := WaitActive;
  IF Wait_EN THEN
    IF Wait_PREV AND NOT Wait_DN THEN
      Wait_ACC := Wait_ACC + TaskPeriodMs;
      IF Wait_ACC >= RetryWaitMs THEN
        Wait_ACC := RetryWaitMs;
        Wait_DN := TRUE;
      END_IF;
    END_IF;
  ELSE
    Wait_ACC := 0;
    Wait_DN := FALSE;
  END_IF;
  Wait_TT := Wait_EN AND NOT Wait_DN;
  Wait_PREV := Wait_EN;
  WaitingRetry := Wait_TT;
  IF Wait_DN THEN
    WaitActive := FALSE;
  END_IF;

  ValveCmd := FillRequest AND Demand AND NOT LockedOut AND NOT WaitActive;

  Open_EN := ValveCmd AND NOT ValveOpen;
  IF Open_EN THEN
    IF Open_PREV AND NOT Open_DN THEN
      Open_ACC := Open_ACC + TaskPeriodMs;
      IF Open_ACC >= OpenTimeoutMs THEN
        Open_ACC := OpenTimeoutMs;
        Open_DN := TRUE;
      END_IF;
    END_IF;
  ELSE
    Open_ACC := 0;
    Open_DN := FALSE;
  END_IF;
  Open_TT := Open_EN AND NOT Open_DN;
  Open_PREV := Open_EN;

  IF ValveCmd AND ValveOpen THEN
    Totalised := Totalised + InflowPerSec * DINT_TO_REAL(TaskPeriodMs) / 1000.0;
  END_IF;

  AckOneShot(CLK := Acknowledge);
  IF AckOneShot.Q THEN
    Retries_ACC := 0;
    Retries_DN := FALSE;
    Open_ACC := 0;
    Open_DN := FALSE;
    Open_EN := FALSE;
    Open_TT := FALSE;
    Open_PREV := FALSE;
    Wait_ACC := 0;
    Wait_DN := FALSE;
    Wait_EN := FALSE;
    Wait_TT := FALSE;
    Wait_PREV := FALSE;
    WaitActive := FALSE;
  END_IF;
END_FUNCTION_BLOCK
