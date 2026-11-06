(* Corner cases where FORTE and matiec could plausibly disagree. semantics_matiec.json is the trace
   of this program under real matiec (st2fb.reference_run), and FORTE must reproduce it. *)
FUNCTION_BLOCK SEMANTICS
VAR_INPUT
  A : INT;
  B : INT;
  GO : BOOL;
END_VAR
VAR_OUTPUT
  RATIO : REAL;
  SUM16 : INT;
  QUOT : INT;
  REMAINDER : INT;
  UNDER : UINT;
  STARTED : BOOL := TRUE;
  OFFSET : DINT := -3;
  DELAY : TIME := T#25ms;
  AFTER_UP : INT;
  AFTER_DOWN : INT;
  STEPS : INT;
  SHRUNK : INT;
  FALLING : BOOL;
  PULSE : BOOL;
  PULSE_ET : TIME;
  OFF_DELAY : BOOL;
  OFF_ET : TIME;
  DOWN_Q : BOOL;
  DOWN_CV : INT;
  CASE_OUT : INT;
  LOWEST : INT;
  CLAMPED : INT;
  MAGNITUDE : INT;
  SELECTED : INT;
END_VAR
VAR
  I : INT;
  LIM : INT;
  COUNTER_U : UINT;
  F1 : F_TRIG;
  P1 : TP;
  O1 : TOF;
  D1 : CTD;
END_VAR
  RATIO := INT_TO_REAL(A) / 3.0;
  SUM16 := A + B;
  IF B <> 0 THEN
    QUOT := A / B;
    REMAINDER := A MOD B;
  END_IF;
  COUNTER_U := COUNTER_U - 1;
  UNDER := COUNTER_U;
  STEPS := 0;
  FOR I := 1 TO 5 BY 2 DO
    STEPS := STEPS + 1;
  END_FOR;
  AFTER_UP := I;
  FOR I := 5 TO 1 BY -1 DO
    STEPS := STEPS + 10;
  END_FOR;
  AFTER_DOWN := I;
  (* matiec re-evaluates TO before every iteration. *)
  LIM := 6;
  SHRUNK := 0;
  FOR I := 1 TO LIM DO
    SHRUNK := SHRUNK + 1;
    LIM := LIM - 1;
  END_FOR;
  F1(CLK := GO);
  FALLING := F1.Q;
  P1(IN := GO, PT := DELAY, Q => PULSE, ET => PULSE_ET);
  O1(IN := GO, PT := DELAY, Q => OFF_DELAY, ET => OFF_ET);
  D1(CD := GO, LD := A > 1000, PV := 3, Q => DOWN_Q, CV => DOWN_CV);
  CASE A OF
    -5: CASE_OUT := 1;
    0..3: CASE_OUT := 2;
    4, 7: CASE_OUT := 3;
  ELSE
    CASE_OUT := 4;
  END_CASE;
  LOWEST := MIN(A, B);
  CLAMPED := LIMIT(-2, A, 5);
  MAGNITUDE := ABS(A);
  SELECTED := SEL(GO, A, B);
END_FUNCTION_BLOCK
