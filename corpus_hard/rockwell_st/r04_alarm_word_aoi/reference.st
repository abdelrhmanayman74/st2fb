(* Hand-written reference for program.l5k. Used only as the matiec oracle, and never shown to a model. A read of bit n
   of a DINT is (x / 2^n) MOD 2 = 1, for non-negative values. Each packed word starts from 0, so setting bit n adds 2^n. *)
FUNCTION_BLOCK AlarmWord_AOI
VAR_INPUT
  Cond0 : BOOL;
  Cond1 : BOOL;
  Cond2 : BOOL;
  MaskWord : DINT;
  DelayMs : DINT;
  AckPB : BOOL;
  TaskPeriodMs : DINT;
END_VAR
VAR_OUTPUT
  AlarmWord : DINT;
  UnackWord : DINT;
  FirstOut : DINT;
  Horn : BOOL;
  Timing : BOOL;
END_VAR
VAR
  T0_EN, T0_TT, T0_DN, T0_PREV : BOOL;
  T0_ACC : DINT;
  T1_EN, T1_TT, T1_DN, T1_PREV : BOOL;
  T1_ACC : DINT;
  T2_EN, T2_TT, T2_DN, T2_PREV : BOOL;
  T2_ACC : DINT;
  AckOneShot : R_TRIG;
  Latched0, Latched1, Latched2 : BOOL;
  Mask0, Mask1, Mask2 : BOOL;
END_VAR
  Mask0 := MaskWord MOD 2 = 1;
  Mask1 := (MaskWord / 2) MOD 2 = 1;
  Mask2 := (MaskWord / 4) MOD 2 = 1;
  T0_EN := Cond0 AND NOT Mask0;
  IF T0_EN THEN
    IF T0_PREV AND NOT T0_DN THEN
      T0_ACC := T0_ACC + TaskPeriodMs;
      IF T0_ACC >= DelayMs THEN
        T0_ACC := DelayMs;
        T0_DN := TRUE;
      END_IF;
    END_IF;
  ELSE
    T0_ACC := 0;
    T0_DN := FALSE;
  END_IF;
  T0_TT := T0_EN AND NOT T0_DN;
  T0_PREV := T0_EN;
  T1_EN := Cond1 AND NOT Mask1;
  IF T1_EN THEN
    IF T1_PREV AND NOT T1_DN THEN
      T1_ACC := T1_ACC + TaskPeriodMs;
      IF T1_ACC >= DelayMs THEN
        T1_ACC := DelayMs;
        T1_DN := TRUE;
      END_IF;
    END_IF;
  ELSE
    T1_ACC := 0;
    T1_DN := FALSE;
  END_IF;
  T1_TT := T1_EN AND NOT T1_DN;
  T1_PREV := T1_EN;
  T2_EN := Cond2 AND NOT Mask2;
  IF T2_EN THEN
    IF T2_PREV AND NOT T2_DN THEN
      T2_ACC := T2_ACC + TaskPeriodMs;
      IF T2_ACC >= DelayMs THEN
        T2_ACC := DelayMs;
        T2_DN := TRUE;
      END_IF;
    END_IF;
  ELSE
    T2_ACC := 0;
    T2_DN := FALSE;
  END_IF;
  T2_TT := T2_EN AND NOT T2_DN;
  T2_PREV := T2_EN;
  Timing := T0_TT OR T1_TT OR T2_TT;

  IF FirstOut = 0 THEN
    IF T0_DN THEN
      FirstOut := 1;
    ELSIF T1_DN THEN
      FirstOut := 2;
    ELSIF T2_DN THEN
      FirstOut := 3;
    END_IF;
  END_IF;

  IF T0_DN THEN
    Latched0 := TRUE;
  END_IF;
  IF T1_DN THEN
    Latched1 := TRUE;
  END_IF;
  IF T2_DN THEN
    Latched2 := TRUE;
  END_IF;

  AckOneShot(CLK := AckPB);
  IF AckOneShot.Q THEN
    Latched0 := FALSE;
    Latched1 := FALSE;
    Latched2 := FALSE;
    IF NOT (T0_DN OR T1_DN OR T2_DN) THEN
      FirstOut := 0;
    END_IF;
  END_IF;

  AlarmWord := 0;
  IF T0_DN THEN
    AlarmWord := AlarmWord + 1;
  END_IF;
  IF T1_DN THEN
    AlarmWord := AlarmWord + 2;
  END_IF;
  IF T2_DN THEN
    AlarmWord := AlarmWord + 4;
  END_IF;
  UnackWord := 0;
  IF Latched0 THEN
    UnackWord := UnackWord + 1;
  END_IF;
  IF Latched1 THEN
    UnackWord := UnackWord + 2;
  END_IF;
  IF Latched2 THEN
    UnackWord := UnackWord + 4;
  END_IF;
  Horn := UnackWord <> 0;
END_FUNCTION_BLOCK
