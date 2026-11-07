(* Solvability control, never shown to a model: the same behaviour in the translator's v1 subset, written for this project.
   The only change is that USINT became INT, and input initial values were dropped since the harness writes every input. *)
FUNCTION_BLOCK GenericBistableDeviceModel
VAR_INPUT
  ActivateCmd : BOOL;
  DeactivateCmd : BOOL;
  cfgActTime : TIME;
  cfgDeactTime : TIME;
  simActFail : BOOL;
  simDeactFail : BOOL;
END_VAR
VAR_OUTPUT
  Activated : BOOL;
  Deactivated : BOOL;
END_VAR
VAR
  TransitionDelay : TON;
  vState : INT := 0;
  vStateOld : INT := 3;
END_VAR
CASE vState OF
  0:
    IF vState <> vStateOld THEN
      TransitionDelay(IN := FALSE);
      vStateOld := vState;
    END_IF;
    TransitionDelay(IN := ActivateCmd AND NOT simActFail, PT := cfgActTime);
    IF TransitionDelay.Q THEN
      vState := 1;
    END_IF;
  1:
    IF vState <> vStateOld THEN
      TransitionDelay(IN := FALSE);
      vStateOld := vState;
    END_IF;
    TransitionDelay(IN := DeactivateCmd AND NOT simDeactFail, PT := cfgDeactTime);
    IF TransitionDelay.Q THEN
      vState := 0;
    END_IF;
END_CASE;
Activated := vState = 1;
Deactivated := vState = 0;
END_FUNCTION_BLOCK
