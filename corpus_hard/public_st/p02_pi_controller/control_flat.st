(* Solvability control, never shown to a model: the same behaviour in the translator's v1 subset, written for this project.
   The helper blocks are inlined, each RETURN became an IF, and the integral limits are the helper's input defaults. *)
FUNCTION_BLOCK FB_PI_Controller
VAR_INPUT
   Reset : BOOL;
   ProcessVariable : REAL;
   Setpoint : REAL;
   Kp : REAL;
   IntegralConstant : REAL;
   RepeatsPerMinute : BOOL;
   MaxLoopOutput : REAL;
   MinLoopOutput : REAL;
   Bias : REAL;
   CycleTimeInSecs : REAL;
END_VAR
VAR_OUTPUT
   Output : REAL;
END_VAR
VAR
   p_Term : REAL;
   i_Term : REAL;
   i_Ki : REAL;
   i_K : REAL;
   i_Pause : BOOL;
   i_integralComponent : REAL;
   i_error : REAL;
   preClampedOutput : REAL;
END_VAR
p_Term := (Setpoint - ProcessVariable) * Kp;

i_Ki := IntegralConstant / SEL(RepeatsPerMinute, 1.0, 60.0);
i_Pause := ((preClampedOutput > MaxLoopOutput) AND (ProcessVariable < Setpoint))
   OR ((preClampedOutput < MinLoopOutput) AND (ProcessVariable > Setpoint));
IF i_Ki <= 0.0 THEN
   i_Term := 0.0;
ELSE
   IF Reset THEN
      i_integralComponent := 0.0;
   END_IF;
   IF Reset OR NOT i_Pause THEN
      i_K := i_Ki * CycleTimeInSecs;
      i_error := Setpoint - ProcessVariable;
      i_integralComponent := i_integralComponent + i_K * i_error;
      IF i_integralComponent > 1000.0 THEN
         i_integralComponent := 1000.0;
      ELSIF i_integralComponent < -1000.0 THEN
         i_integralComponent := -1000.0;
      END_IF;
      i_Term := i_integralComponent;
   END_IF;
END_IF;

preClampedOutput := p_Term + i_Term + Bias;
Output := LIMIT(MinLoopOutput, preClampedOutput, MaxLoopOutput);
END_FUNCTION_BLOCK
