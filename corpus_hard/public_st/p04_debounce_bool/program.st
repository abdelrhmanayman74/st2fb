(* From anjlab/codebox, DebounceBool, by Sergey A Glukhov. Copyright 2025 AnjLab. Apache License 2.0, see LICENSE in this
   directory. *)
FUNCTION_BLOCK DebounceBool
VAR_INPUT
  inputSignal : BOOL;
  onDelay : TIME;
  offDelay : TIME;
END_VAR
VAR_OUTPUT
  debouncedOutput : BOOL;
END_VAR
VAR
  tonTimer : TON;
  tofTimer : TON;
END_VAR
(* Rising edge handling — start TON if input is TRUE and output is still FALSE *)
tonTimer(IN := inputSignal AND NOT debouncedOutput, PT := onDelay);

(* Falling edge handling — start TOF if input is FALSE and output is still TRUE *)
tofTimer(IN := NOT inputSignal AND debouncedOutput, PT := offDelay);

(* Update the output based on timers *)
IF tonTimer.IN AND tonTimer.Q THEN
    debouncedOutput := TRUE;
ELSIF tofTimer.IN AND tofTimer.Q THEN
    debouncedOutput := FALSE;
END_IF;
END_FUNCTION_BLOCK
