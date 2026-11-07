(* Hand-written reference for program.scl. Used only as the matiec oracle, and never shown to a model. *)
FUNCTION_BLOCK FB_ConveyorStarter
VAR_INPUT
  i_start : BOOL;
  i_stop : BOOL;
  i_estopOk : BOOL;
  i_overload : BOOL;
  i_reset : BOOL;
  i_hornTime : TIME;
  i_coastTime : TIME;
END_VAR
VAR_OUTPUT
  o_run : BOOL;
  o_horn : BOOL;
  o_tripped : BOOL;
  o_coasting : BOOL;
  o_hornElapsed : TIME;
END_VAR
VAR
  statRunRequest : BOOL;
  statTrip : BOOL;
  statHornPreset : TIME;
  statCoastPreset : TIME;
  statStartEdge : R_TRIG;
  statHornTimer : TON;
  statCoastTimer : TOF;
  tempPermit : BOOL;
END_VAR
  IF i_overload OR NOT i_estopOk THEN
    statTrip := TRUE;
  ELSIF i_reset THEN
    statTrip := FALSE;
  END_IF;
  tempPermit := i_estopOk AND NOT statTrip;

  IF NOT statRunRequest THEN
    statHornPreset := i_hornTime;
  END_IF;
  IF o_run THEN
    statCoastPreset := i_coastTime;
  END_IF;
  statStartEdge(CLK := i_start);
  IF i_stop OR NOT tempPermit THEN
    statRunRequest := FALSE;
  ELSIF statStartEdge.Q THEN
    statRunRequest := TRUE;
  END_IF;

  statHornTimer(IN := statRunRequest, PT := statHornPreset, ET => o_hornElapsed);
  o_horn := statRunRequest AND NOT statHornTimer.Q;
  o_run := statRunRequest AND statHornTimer.Q;

  statCoastTimer(IN := o_run, PT := statCoastPreset);
  o_coasting := statCoastTimer.Q AND NOT o_run;
  o_tripped := statTrip;
END_FUNCTION_BLOCK
