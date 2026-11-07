(* Solvability control, never shown to a model: the same behaviour in the translator's v1 subset. Records became
   variables, EXIT became a loop condition. *)
FUNCTION_BLOCK PUMP_DUTY_SELECT
VAR_INPUT
  DEMAND : INT;
  AVAIL_1, AVAIL_2, AVAIL_3 : BOOL;
  RESET_TICKS : BOOL;
END_VAR
VAR_OUTPUT
  RUN_1, RUN_2, RUN_3 : BOOL;
  TICKS_1, TICKS_2, TICKS_3 : DINT;
  STARTS_TOTAL : INT;
  UNMET : INT;
END_VAR
VAR
  STARTS_1, STARTS_2, STARTS_3 : INT;
  WAS_1, WAS_2, WAS_3 : BOOL;
  PREV_DEMAND : INT;
  N : INT;
  BEST : INT;
  BEST_SCORE : DINT;
  SCORE : DINT;
  CHANGED : BOOL;
  SEARCHING : BOOL;
END_VAR
  CHANGED := (DEMAND <> PREV_DEMAND) OR (RUN_1 AND NOT AVAIL_1) OR (RUN_2 AND NOT AVAIL_2) OR (RUN_3 AND NOT AVAIL_3);
  PREV_DEMAND := DEMAND;

  IF CHANGED THEN
    WAS_1 := RUN_1;
    WAS_2 := RUN_2;
    WAS_3 := RUN_3;
    RUN_1 := FALSE;
    RUN_2 := FALSE;
    RUN_3 := FALSE;
    UNMET := 0;
    N := 1;
    SEARCHING := N <= DEMAND;
    WHILE SEARCHING DO
      BEST := 0;
      BEST_SCORE := 2147483647;
      IF AVAIL_1 AND NOT RUN_1 THEN
        SCORE := TICKS_1 + 5 * INT_TO_DINT(STARTS_1);
        IF SCORE < BEST_SCORE THEN
          BEST := 1;
          BEST_SCORE := SCORE;
        END_IF;
      END_IF;
      IF AVAIL_2 AND NOT RUN_2 THEN
        SCORE := TICKS_2 + 5 * INT_TO_DINT(STARTS_2);
        IF SCORE < BEST_SCORE THEN
          BEST := 2;
          BEST_SCORE := SCORE;
        END_IF;
      END_IF;
      IF AVAIL_3 AND NOT RUN_3 THEN
        SCORE := TICKS_3 + 5 * INT_TO_DINT(STARTS_3);
        IF SCORE < BEST_SCORE THEN
          BEST := 3;
          BEST_SCORE := SCORE;
        END_IF;
      END_IF;
      CASE BEST OF
        0:
          UNMET := DEMAND - N + 1;
          SEARCHING := FALSE;
        1:
          RUN_1 := TRUE;
          IF NOT WAS_1 THEN
            STARTS_1 := STARTS_1 + 1;
            STARTS_TOTAL := STARTS_TOTAL + 1;
          END_IF;
        2:
          RUN_2 := TRUE;
          IF NOT WAS_2 THEN
            STARTS_2 := STARTS_2 + 1;
            STARTS_TOTAL := STARTS_TOTAL + 1;
          END_IF;
        3:
          RUN_3 := TRUE;
          IF NOT WAS_3 THEN
            STARTS_3 := STARTS_3 + 1;
            STARTS_TOTAL := STARTS_TOTAL + 1;
          END_IF;
      END_CASE;
      N := N + 1;
      IF N > DEMAND THEN
        SEARCHING := FALSE;
      END_IF;
    END_WHILE;
  END_IF;

  IF RESET_TICKS THEN
    TICKS_1 := 0;
    TICKS_2 := 0;
    TICKS_3 := 0;
  ELSE
    IF RUN_1 THEN
      TICKS_1 := TICKS_1 + 1;
    END_IF;
    IF RUN_2 THEN
      TICKS_2 := TICKS_2 + 1;
    END_IF;
    IF RUN_3 THEN
      TICKS_3 := TICKS_3 + 1;
    END_IF;
  END_IF;
END_FUNCTION_BLOCK
