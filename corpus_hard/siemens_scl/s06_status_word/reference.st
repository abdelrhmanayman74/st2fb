(* Hand-written reference for program.scl. Used only as the matiec oracle, and never shown to a model.
   A slice read x.%Xn is (x / 2^n) MOD 2 = 1, and packing adds 2^n when the bit is set. *)
FUNCTION_BLOCK FB_DriveStatus
VAR_INPUT
  i_controlWord : UINT;
  i_speedRef : INT;
  i_driveFault : BOOL;
  i_atSpeed : BOOL;
END_VAR
VAR_OUTPUT
  o_statusWord : UINT;
  o_runForward : BOOL;
  o_runReverse : BOOL;
  o_speedPercent : REAL;
  o_faultCount : UINT;
END_VAR
VAR
  statFaultLatched : BOOL;
  statFaultEdge : R_TRIG;
  tempCtl0, tempCtl1, tempCtl2, tempCtl7 : BOOL;
  tempStat : UINT;
END_VAR
  tempCtl0 := i_controlWord MOD 2 = 1;
  tempCtl1 := (i_controlWord / 2) MOD 2 = 1;
  tempCtl2 := (i_controlWord / 4) MOD 2 = 1;
  tempCtl7 := (i_controlWord / 128) MOD 2 = 1;
  statFaultEdge(CLK := i_driveFault);
  IF statFaultEdge.Q THEN
    o_faultCount := o_faultCount + 1;
  END_IF;
  IF i_driveFault THEN
    statFaultLatched := TRUE;
  ELSIF tempCtl7 THEN
    statFaultLatched := FALSE;
  END_IF;

  o_runForward := tempCtl0 AND tempCtl1 AND NOT tempCtl2 AND NOT statFaultLatched;
  o_runReverse := tempCtl0 AND tempCtl1 AND tempCtl2 AND NOT statFaultLatched;
  IF o_runForward OR o_runReverse THEN
    o_speedPercent := INT_TO_REAL(i_speedRef) * 100.0 / 16384.0;
  ELSE
    o_speedPercent := 0.0;
  END_IF;

  tempStat := 0;
  IF tempCtl0 AND NOT statFaultLatched THEN
    tempStat := tempStat + 1;
  END_IF;
  IF o_runForward OR o_runReverse THEN
    tempStat := tempStat + 2;
  END_IF;
  IF o_runReverse THEN
    tempStat := tempStat + 4;
  END_IF;
  IF statFaultLatched THEN
    tempStat := tempStat + 8;
  END_IF;
  IF i_atSpeed AND (o_runForward OR o_runReverse) THEN
    tempStat := tempStat + 16;
  END_IF;
  o_statusWord := tempStat;
END_FUNCTION_BLOCK
