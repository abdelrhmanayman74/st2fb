(* Solvability control, never shown to a model: the same behaviour in the translator's v1 subset. *)
FUNCTION_BLOCK FB_LeadLag
VAR_INPUT
  i_rotate : BOOL;
  i_lagDemand : BOOL;
  i_avail1 : BOOL;
  i_avail2 : BOOL;
  i_avail3 : BOOL;
END_VAR
VAR_OUTPUT
  o_lead : INT;
  o_lag : INT;
  o_run1 : BOOL;
  o_run2 : BOOL;
  o_run3 : BOOL;
  o_rotations : DINT;
END_VAR
VAR
  statRotateEdge : R_TRIG;
  tempIdx : INT;
  tempCandidate : INT;
  tempOffset : INT;
  leadOk : BOOL;
  thisOk : BOOL;
END_VAR
  statRotateEdge(CLK := i_rotate);
  CASE o_lead OF
    0, 1:
      leadOk := i_avail1;
    2:
      leadOk := i_avail2;
  ELSE
    leadOk := i_avail3;
  END_CASE;
  IF statRotateEdge.Q OR o_lead = 0 OR NOT leadOk THEN
    tempCandidate := 0;
    FOR tempOffset := 1 TO 3 DO
      IF tempCandidate = 0 THEN
        tempIdx := (o_lead + tempOffset - 1) MOD 3 + 1;
        CASE tempIdx OF
          1:
            thisOk := i_avail1;
          2:
            thisOk := i_avail2;
        ELSE
          thisOk := i_avail3;
        END_CASE;
        IF thisOk THEN
          tempCandidate := tempIdx;
        END_IF;
      END_IF;
    END_FOR;
    IF tempCandidate <> o_lead THEN
      o_lead := tempCandidate;
      o_rotations := o_rotations + 1;
    END_IF;
  END_IF;

  o_lag := 0;
  IF i_lagDemand AND o_lead <> 0 THEN
    FOR tempOffset := 1 TO 2 DO
      IF o_lag = 0 THEN
        tempIdx := (o_lead + tempOffset - 1) MOD 3 + 1;
        CASE tempIdx OF
          1:
            thisOk := i_avail1;
          2:
            thisOk := i_avail2;
        ELSE
          thisOk := i_avail3;
        END_CASE;
        IF thisOk THEN
          o_lag := tempIdx;
        END_IF;
      END_IF;
    END_FOR;
  END_IF;

  o_run1 := o_lead = 1 OR o_lag = 1;
  o_run2 := o_lead = 2 OR o_lag = 2;
  o_run3 := o_lead = 3 OR o_lag = 3;
END_FUNCTION_BLOCK
