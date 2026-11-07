(* From tkucic/plc_hello_mixing_tank, GenericBistableDeviceModel. Copyright (c) 2021 Toni Kucic. MIT licence, see LICENSE
   in this directory. *)
FUNCTION_BLOCK GenericBistableDeviceModel
VAR_INPUT
  ActivateCmd : BOOL;
  DeactivateCmd : BOOL;
  cfgActTime : TIME := TIME#1s0ms;
  cfgDeactTime : TIME := TIME#1s0ms;
  simActFail : BOOL;
  simDeactFail : BOOL;
END_VAR
VAR_OUTPUT
  Activated : BOOL;
  Deactivated : BOOL;
END_VAR
VAR
  TransitionDelay : TON;
  vState : USINT := 0;
  vStateOld : USINT := 3;
END_VAR
CASE vState OF
	0: (*Deactivated*)
		(*On entry do:*)
		IF vState <> vStateOld THEN
			(*Reset timer*)
			TransitionDelay(IN:=FALSE);
			vStateOld := vState;
		END_IF;
		TransitionDelay(IN:=ActivateCmd AND NOT simActFail, PT:=cfgActTime);
		IF TransitionDelay.Q THEN
			vState := 1;
		END_IF;
	1: (*Activated*)
		(*On entry do:*)
		IF vState <> vStateOld THEN
			(*Reset timer*)
			TransitionDelay(IN:=FALSE);
			vStateOld := vState;
		END_IF;
		TransitionDelay(IN:=DeactivateCmd AND NOT simDeactFail, PT:=cfgDeactTime);
		IF TransitionDelay.Q THEN
			vState := 0;
		END_IF;
END_CASE;
Activated := vState = 1;
Deactivated := vState = 0;
END_FUNCTION_BLOCK
