(* Hand-written reference for program.scl. Used only as the matiec oracle, and never shown to a model. *)
FUNCTION_BLOCK FB_PackagingCounter
VAR_INPUT
  i_photoEye : BOOL;
  i_rejectRequest : BOOL;
  i_resetCount : BOOL;
  i_batchSize : INT;
  i_rejectPulse : TIME;
  i_jamTime : TIME;
  i_clearJam : BOOL;
  i_maxSpeed : REAL;
  i_speedRef : REAL;
END_VAR
VAR_OUTPUT
  o_count : INT;
  o_batchFull : BOOL;
  o_reject : BOOL;
  o_rejectElapsed : TIME;
  o_jam : BOOL;
  o_speed : REAL;
  o_rejected : INT;
END_VAR
VAR
  statEyePrev : BOOL;
  statRequestPrev : BOOL;
  statRejectPrev : BOOL;
  statRejectPreset : TIME;
  statJamPreset : TIME;
  statRejectPulse : TP;
  statJamTimer : TON;
  tempCartonEdge : BOOL;
  tempRejectEdge : BOOL;
END_VAR
  tempCartonEdge := statEyePrev AND NOT i_photoEye;
  IF i_resetCount THEN
    o_count := 0;
  ELSIF tempCartonEdge AND (o_count < i_batchSize) THEN
    o_count := o_count + 1;
  END_IF;
  o_batchFull := o_count >= i_batchSize;

  tempRejectEdge := statRequestPrev AND NOT i_rejectRequest;
  statRequestPrev := i_rejectRequest;
  IF NOT o_reject THEN
    statRejectPreset := i_rejectPulse;
  END_IF;
  statRejectPulse(IN := tempRejectEdge AND NOT o_jam, PT := statRejectPreset, Q => o_reject, ET => o_rejectElapsed);
  IF i_resetCount THEN
    o_rejected := 0;
  ELSIF o_reject AND NOT statRejectPrev THEN
    o_rejected := o_rejected + 1;
  END_IF;
  statRejectPrev := o_reject;

  IF NOT statEyePrev THEN
    statJamPreset := i_jamTime;
  END_IF;
  statEyePrev := i_photoEye;
  statJamTimer(IN := i_photoEye, PT := statJamPreset);
  IF statJamTimer.Q THEN
    o_jam := TRUE;
  ELSIF i_clearJam THEN
    o_jam := FALSE;
  END_IF;
  o_speed := SEL(o_jam OR o_batchFull, MIN(i_speedRef, i_maxSpeed), 0.0);
END_FUNCTION_BLOCK
