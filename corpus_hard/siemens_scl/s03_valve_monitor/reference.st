(* Hand-written reference for program.scl. Used only as the matiec oracle, and never shown to a model.
   T_ADD is TIME + TIME. RETURN became an enclosing IF. *)
FUNCTION_BLOCK FB_ValveMonitor
VAR_INPUT
  i_openCmd : BOOL;
  i_atOpen : BOOL;
  i_atClosed : BOOL;
  i_maintenance : BOOL;
  i_ack : BOOL;
  i_travelTime : TIME;
  i_margin : TIME;
END_VAR
VAR_OUTPUT
  o_coil : BOOL;
  o_fault : BOOL;
  o_opening : BOOL;
  o_closing : BOOL;
  o_openElapsed : TIME;
  o_closeElapsed : TIME;
  o_faultCount : DINT;
END_VAR
VAR
  statOpenTimer : TON;
  statCloseTimer : TON;
  statOpenBudget : TIME;
  statCloseBudget : TIME;
  statFaultEdge : R_TRIG;
  tempBudget : TIME;
END_VAR
  IF NOT i_maintenance THEN
    tempBudget := i_travelTime + i_margin;
    o_coil := i_openCmd AND NOT o_fault;
    IF NOT o_opening THEN
      statOpenBudget := tempBudget;
    END_IF;
    IF NOT o_closing THEN
      statCloseBudget := tempBudget;
    END_IF;
    o_opening := o_coil AND NOT i_atOpen;
    o_closing := NOT o_coil AND NOT i_atClosed;
    statOpenTimer(IN := o_opening, PT := statOpenBudget, ET => o_openElapsed);
    statCloseTimer(IN := o_closing, PT := statCloseBudget, ET => o_closeElapsed);

    IF i_ack THEN
      o_fault := FALSE;
    ELSIF statOpenTimer.Q OR statCloseTimer.Q OR (i_atOpen AND i_atClosed) THEN
      o_fault := TRUE;
    END_IF;
    statFaultEdge(CLK := o_fault);
    IF statFaultEdge.Q THEN
      o_faultCount := o_faultCount + 1;
    END_IF;
  END_IF;
END_FUNCTION_BLOCK
