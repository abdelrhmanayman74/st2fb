(* Alarm log held as a ring of records. *)
TYPE
  ALARM_EVENT : STRUCT
    CODE : INT;
    ACKED : BOOL;
    AGE : DINT;
  END_STRUCT;
END_TYPE

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
  RING : ARRAY[1..4] OF ALARM_EVENT;
  HEAD : INT := 1;
  USED : INT;
  I : INT;
  SLOT : INT;
  PREV_CODE : INT;
  ACK_EDGE : R_TRIG;
END_VAR
  ACK_EDGE(CLK := ACK_OLDEST);

  IF CLEAR_ALL THEN
    FOR I := 1 TO 4 DO
      RING[I].CODE := 0;
      RING[I].ACKED := FALSE;
      RING[I].AGE := 0;
    END_FOR;
    HEAD := 1;
    USED := 0;
    NEWEST_CODE := 0;
  ELSIF (RAISE_CODE <> 0) AND (RAISE_CODE <> PREV_CODE) THEN
    (* A full ring overwrites the oldest record. *)
    IF USED = 4 THEN
      OVERWRITES := OVERWRITES + 1;
    ELSE
      USED := USED + 1;
    END_IF;
    RING[HEAD].CODE := RAISE_CODE;
    RING[HEAD].ACKED := FALSE;
    RING[HEAD].AGE := 0;
    NEWEST_CODE := RAISE_CODE;
    HEAD := HEAD MOD 4 + 1;
  END_IF;
  PREV_CODE := RAISE_CODE;

  (* Walk from the oldest record to the newest: acknowledge one on an edge, and find the oldest still unacknowledged. *)
  OLDEST_UNACKED := 0;
  OLDEST_AGE := 0;
  UNACKED := 0;
  FOR I := 1 TO USED DO
    SLOT := (HEAD - USED + I + 3) MOD 4 + 1;
    RING[SLOT].AGE := RING[SLOT].AGE + 1;
  END_FOR;
  IF ACK_EDGE.Q THEN
    FOR I := 1 TO USED DO
      SLOT := (HEAD - USED + I + 3) MOD 4 + 1;
      IF NOT RING[SLOT].ACKED THEN
        RING[SLOT].ACKED := TRUE;
        EXIT;
      END_IF;
    END_FOR;
  END_IF;
  FOR I := USED TO 1 BY -1 DO
    SLOT := (HEAD - USED + I + 3) MOD 4 + 1;
    IF NOT RING[SLOT].ACKED THEN
      UNACKED := UNACKED + 1;
      OLDEST_UNACKED := RING[SLOT].CODE;
      OLDEST_AGE := RING[SLOT].AGE;
    END_IF;
  END_FOR;
END_FUNCTION_BLOCK
