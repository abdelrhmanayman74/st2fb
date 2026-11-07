(* From Intecre/twincat-utils, FB_P_Control, FB_I_Controller and FB_PI_Controller. Copyright (c) 2022 Intecre Ltd. MIT licence,
   see LICENSE in this directory. *)
FUNCTION_BLOCK FB_P_Control
VAR_INPUT
   ProcessVariable : REAL;
   Setpoint : REAL;
   Kp : REAL;
END_VAR
VAR_OUTPUT
   Term : REAL;
END_VAR
Term := (Setpoint - ProcessVariable) * Kp;
END_FUNCTION_BLOCK

FUNCTION_BLOCK FB_I_Controller
VAR_INPUT
   ProcessVariable : REAL;
   Setpoint : REAL;
   Ki : REAL; (* Resets per unitTime *)
   MaxIntegralComponent : REAL := 1000.0; (* max absolute value of Output *)
   MinIntegralComponent : REAL := -1000.0; (* min abs value of output. *)
   Pause : BOOL; (* pause integration *)
   Reset : BOOL; (* reset integration. *)
   CycleTimeInSecs : REAL;
END_VAR
VAR_OUTPUT
   Term : REAL;
END_VAR
VAR
   _Ki : REAL; (* include cycle time. *)
   integralComponent : REAL;
   error : REAL;
   
END_VAR
(* if block turned off, do nothing. *)
IF Ki <= 0.0 THEN
   Term := 0.0;
   RETURN;
END_IF;

IF Reset THEN
   integralComponent := 0.0;
ELSIF Pause THEN
   RETURN;
END_IF;

(* get gain with scan time. *)

_Ki := Ki * CycleTimeInSecs;

(* get this error. *)
error := Setpoint - ProcessVariable;

(* sum errors (gains included) *)
integralComponent := integralComponent + _Ki * error;

(* clamp output, and reverse engineer integral accordingly. *)
IF integralComponent > MaxIntegralComponent THEN
   integralComponent := MaxIntegralComponent;
ELSIF integralComponent < MinIntegralComponent THEN
   integralComponent := MinIntegralComponent;
END_IF;

(* derive integral output. *)
Term := integralComponent;
END_FUNCTION_BLOCK

(* st2fb:dut *)
FUNCTION_BLOCK FB_PI_Controller
VAR_INPUT
   Reset : BOOL; (* Reset integral component *)
   ProcessVariable : REAL;
   Setpoint : REAL;
   Kp : REAL;
   IntegralConstant : REAL; (* Repeats per minute *)
   RepeatsPerMinute : BOOL := TRUE; (* if false, repeats per second. *)
   MaxLoopOutput : REAL;
   MinLoopOutput : REAL;
   Bias : REAL;
   CycleTimeInSecs : REAL;
END_VAR
VAR_OUTPUT
   Output : REAL;
END_VAR
VAR
   p : FB_P_Control;
   i : FB_I_Controller;
   preClampedOutput : REAL;
END_VAR
p(
   ProcessVariable := ProcessVariable,
   Setpoint := Setpoint,
   Kp := Kp
);

i(
   ProcessVariable := ProcessVariable,
   Setpoint := Setpoint,
   Ki := IntegralConstant
      / SEL(RepeatsPerMinute, 1.0, 60.0), (* normalising to repeats per minute. FB_I_COntroller block works in repeats per second natively. *)
   Pause :=
      ((preClampedOutput > MaxLoopOutput) AND (ProcessVariable < Setpoint))
      OR ((preClampedOutput < MinLoopOutput) AND (ProcessVariable > Setpoint)),
   Reset := Reset,
   CycleTimeInSecs := CycleTimeInSecs
);

(* caclculate output *)
preClampedOutput := p.Term + i.Term + Bias;
Output := LIMIT(MinLoopOutput, preClampedOutput, MaxLoopOutput); (* clamp the output *)
END_FUNCTION_BLOCK
