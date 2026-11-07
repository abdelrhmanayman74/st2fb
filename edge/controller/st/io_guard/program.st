(* Field-side guard in front of the supervisor. Same pipeline as the supervisor: ST -> .fbt -> FORTE C++.
   Input registers arrive as UINT 0/1. COMMS_OK needs a heartbeat that keeps moving, because FORTE's Modbus
   layer gives the application no signal when polling fails: the last values simply stay on the pins.
   A stuck level sensor is an unchanged reading while the link is good. *)
FUNCTION_BLOCK IO_GUARD
VAR_INPUT
  R_AUTO : UINT;
  R_ACK : UINT;
  R_FB_1 : UINT;
  R_FB_2 : UINT;
  R_TRIP_1 : UINT;
  R_TRIP_2 : UINT;
  HEARTBEAT : UINT;
  RAW_LEVEL : REAL;
  STUCK_EPS : REAL;
  COMMS_TIMEOUT : TIME;
  STUCK_TIME : TIME;
END_VAR
VAR_OUTPUT
  AUTO_MODE : BOOL;
  ACK : BOOL;
  FB_1 : BOOL;
  FB_2 : BOOL;
  TRIP_1 : BOOL;
  TRIP_2 : BOOL;
  COMMS_OK : BOOL;
  SENSOR_FAULT : BOOL;
END_VAR
VAR
  COMMS_TIMER : TON;
  STUCK_TIMER : TON;
  ACK_EDGE : R_TRIG;
  FAULT_LATCH : SR;
  LAST_HEARTBEAT : UINT;
  LAST_LEVEL : REAL;
  SEEN_BEAT : BOOL;
  UNCHANGED : BOOL;
  DELTA : REAL;
END_VAR
  IF HEARTBEAT <> LAST_HEARTBEAT THEN
    SEEN_BEAT := TRUE;
  END_IF;
  COMMS_TIMER(IN := HEARTBEAT = LAST_HEARTBEAT, PT := COMMS_TIMEOUT);
  LAST_HEARTBEAT := HEARTBEAT;
  COMMS_OK := SEEN_BEAT AND NOT COMMS_TIMER.Q;

  DELTA := RAW_LEVEL - LAST_LEVEL;
  UNCHANGED := (DELTA <= STUCK_EPS) AND (DELTA >= -STUCK_EPS);
  LAST_LEVEL := RAW_LEVEL;
  STUCK_TIMER(IN := UNCHANGED AND COMMS_OK, PT := STUCK_TIME);

  ACK := R_ACK <> 0;
  ACK_EDGE(CLK := ACK);
  FAULT_LATCH(S1 := STUCK_TIMER.Q, R := ACK_EDGE.Q);
  SENSOR_FAULT := FAULT_LATCH.Q1;

  AUTO_MODE := (R_AUTO <> 0) AND COMMS_OK AND NOT SENSOR_FAULT;
  FB_1 := R_FB_1 <> 0;
  FB_2 := R_FB_2 <> 0;
  TRIP_1 := R_TRIP_1 <> 0;
  TRIP_2 := R_TRIP_2 <> 0;
END_FUNCTION_BLOCK
