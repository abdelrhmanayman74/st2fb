(* Hand-written reference for program.scl. Used only as the matiec oracle, and never shown to a model.
   ROUND is REAL_TO_DINT, whose matiec library code rounds half to even. SQR(x) is x ** 2.0. RETURN became an enclosing IF. *)
FUNCTION_BLOCK FB_HeaterPI
VAR_INPUT
  i_enable : BOOL;
  i_setpoint : REAL;
  i_measured : REAL;
  i_kp : REAL;
  i_ki : REAL;
  i_outMax : REAL;
  i_deadband : REAL;
END_VAR
VAR_OUTPUT
  o_output : REAL;
  o_pwmTicks : INT;
  o_saturated : BOOL;
  o_error : REAL;
  o_quality : REAL;
END_VAR
VAR
  statIntegral : REAL;
  statFirstRun : BOOL := TRUE;
  tempUnclamped : REAL;
  tempErrorAbs : REAL;
END_VAR
  IF NOT i_enable THEN
    o_saturated := FALSE;
    statFirstRun := TRUE;
  ELSE
    IF statFirstRun THEN
      statIntegral := o_output;
      statFirstRun := FALSE;
    END_IF;

    o_error := i_setpoint - i_measured;
    tempErrorAbs := ABS(o_error);
    IF tempErrorAbs < i_deadband THEN
      o_error := 0.0;
    END_IF;
    tempUnclamped := i_kp * o_error + statIntegral + i_ki * o_error;
    o_output := LIMIT(0.0, tempUnclamped, i_outMax);
    o_saturated := o_output <> tempUnclamped;
    IF NOT o_saturated THEN
      statIntegral := statIntegral + i_ki * o_error;
    END_IF;

    o_pwmTicks := DINT_TO_INT(REAL_TO_DINT(o_output * 10.0));
    o_quality := SQRT(o_error ** 2.0 + 1.0);
  END_IF;
END_FUNCTION_BLOCK
