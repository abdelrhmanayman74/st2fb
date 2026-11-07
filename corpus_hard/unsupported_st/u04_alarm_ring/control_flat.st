(* Solvability control, never shown to a model: the same behaviour in the translator's v1 subset. Each array element
   became three variables, each indexed access a CASE, and EXIT a DONE flag in the loop. *)
FUNCTION_BLOCK ALARM_RING
VAR_INPUT
  RAISE_CODE : INT;
  ACK_OLDEST : BOOL;
  CLEAR_ALL : BOOL;
END_VAR
VAR_OUTPUT
  NEWEST_CODE : INT;
  OLDEST_UNACKED : INT;
  OLDEST_AGE : DINT;
  UNACKED : INT;
  OVERWRITES : DINT;
END_VAR
VAR
  C1 : INT;
  A1 : BOOL;
  G1 : DINT;
  C2 : INT;
  A2 : BOOL;
  G2 : DINT;
  C3 : INT;
  A3 : BOOL;
  G3 : DINT;
  C4 : INT;
  A4 : BOOL;
  G4 : DINT;
  HEAD : INT := 1;
  USED : INT;
  I : INT;
  SLOT : INT;
  PREV_CODE : INT;
  ACK_EDGE : R_TRIG;
  DONE : BOOL;
END_VAR
  ACK_EDGE(CLK := ACK_OLDEST);

  IF CLEAR_ALL THEN
    C1 := 0;
    A1 := FALSE;
    G1 := 0;
    C2 := 0;
    A2 := FALSE;
    G2 := 0;
    C3 := 0;
    A3 := FALSE;
    G3 := 0;
    C4 := 0;
    A4 := FALSE;
    G4 := 0;
    HEAD := 1;
    USED := 0;
    NEWEST_CODE := 0;
  ELSIF (RAISE_CODE <> 0) AND (RAISE_CODE <> PREV_CODE) THEN
    IF USED = 4 THEN
      OVERWRITES := OVERWRITES + 1;
    ELSE
      USED := USED + 1;
    END_IF;
    CASE HEAD OF
      1:
        C1 := RAISE_CODE;
        A1 := FALSE;
        G1 := 0;
      2:
        C2 := RAISE_CODE;
        A2 := FALSE;
        G2 := 0;
      3:
        C3 := RAISE_CODE;
        A3 := FALSE;
        G3 := 0;
      4:
        C4 := RAISE_CODE;
        A4 := FALSE;
        G4 := 0;
    END_CASE;
    NEWEST_CODE := RAISE_CODE;
    HEAD := HEAD MOD 4 + 1;
  END_IF;
  PREV_CODE := RAISE_CODE;

  OLDEST_UNACKED := 0;
  OLDEST_AGE := 0;
  UNACKED := 0;
  FOR I := 1 TO USED DO
    SLOT := (HEAD - USED + I + 3) MOD 4 + 1;
    CASE SLOT OF
      1:
        G1 := G1 + 1;
      2:
        G2 := G2 + 1;
      3:
        G3 := G3 + 1;
      4:
        G4 := G4 + 1;
    END_CASE;
  END_FOR;
  IF ACK_EDGE.Q THEN
    DONE := FALSE;
    FOR I := 1 TO USED DO
      SLOT := (HEAD - USED + I + 3) MOD 4 + 1;
      IF NOT DONE THEN
      CASE SLOT OF
        1:
          IF NOT A1 THEN
            A1 := TRUE;
            DONE := TRUE;
          END_IF;
        2:
          IF NOT A2 THEN
            A2 := TRUE;
            DONE := TRUE;
          END_IF;
        3:
          IF NOT A3 THEN
            A3 := TRUE;
            DONE := TRUE;
          END_IF;
        4:
          IF NOT A4 THEN
            A4 := TRUE;
            DONE := TRUE;
          END_IF;
      END_CASE;
      END_IF;
    END_FOR;
  END_IF;
  FOR I := USED TO 1 BY -1 DO
    SLOT := (HEAD - USED + I + 3) MOD 4 + 1;
    CASE SLOT OF
      1:
        IF NOT A1 THEN
          UNACKED := UNACKED + 1;
          OLDEST_UNACKED := C1;
          OLDEST_AGE := G1;
        END_IF;
      2:
        IF NOT A2 THEN
          UNACKED := UNACKED + 1;
          OLDEST_UNACKED := C2;
          OLDEST_AGE := G2;
        END_IF;
      3:
        IF NOT A3 THEN
          UNACKED := UNACKED + 1;
          OLDEST_UNACKED := C3;
          OLDEST_AGE := G3;
        END_IF;
      4:
        IF NOT A4 THEN
          UNACKED := UNACKED + 1;
          OLDEST_UNACKED := C4;
          OLDEST_AGE := G4;
        END_IF;
    END_CASE;
  END_FOR;
END_FUNCTION_BLOCK
