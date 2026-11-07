(* Hand-written reference for program.scl. Used only as the matiec oracle, and never shown to a model.
   The record array is kept as a BOOL array, since runTicks is never used. CONTINUE became an IF around the rest of the
   loop body. *)
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
  statAvailable : ARRAY[1..3] OF BOOL;
  statRotateEdge : R_TRIG;
  tempIdx : INT;
  tempCandidate : INT;
  tempOffset : INT;
END_VAR
  statAvailable[1] := i_avail1;
  statAvailable[2] := i_avail2;
  statAvailable[3] := i_avail3;

  statRotateEdge(CLK := i_rotate);
  IF statRotateEdge.Q OR o_lead = 0 OR NOT statAvailable[MAX(o_lead, 1)] THEN
    tempCandidate := 0;
    FOR tempOffset := 1 TO 3 DO
      tempIdx := (o_lead + tempOffset - 1) MOD 3 + 1;
      IF statAvailable[tempIdx] THEN
        tempCandidate := tempIdx;
        EXIT;
      END_IF;
    END_FOR;
    IF tempCandidate <> o_lead THEN
      o_lead := tempCandidate;
      o_rotations := o_rotations + 1;
    END_IF;
  END_IF;

  o_lag := 0;
  IF i_lagDemand AND o_lead <> 0 THEN
    FOR tempOffset := 1 TO 3 - 1 DO
      tempIdx := (o_lead + tempOffset - 1) MOD 3 + 1;
      IF statAvailable[tempIdx] THEN
        o_lag := tempIdx;
        EXIT;
      END_IF;
    END_FOR;
  END_IF;

  o_run1 := o_lead = 1 OR o_lag = 1;
  o_run2 := o_lead = 2 OR o_lag = 2;
  o_run3 := o_lead = 3 OR o_lag = 3;
END_FUNCTION_BLOCK
