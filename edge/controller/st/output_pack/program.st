(* FORTE's Modbus layer writes a BOOL as one byte, which does not fit a 16-bit register, and it splits
   separate address ranges into separate requests. One flat block of UINT, sent as a single FC16 with
   the fencing token first, keeps the write atomic. EPOCH is written by the agent through DEV_MGR. *)
FUNCTION_BLOCK OUTPUT_PACK
VAR_INPUT
  EPOCH : UINT;
  PUMP_1 : BOOL;
  PUMP_2 : BOOL;
  STATE_NO : INT;
  LEAD_IS_2 : BOOL;
  HIGH_ALARM : BOOL;
  STATION_FAULT : BOOL;
  COMMS_OK : BOOL;
  SENSOR_FAULT : BOOL;
END_VAR
VAR_OUTPUT
  W_TOKEN : UINT;
  W_PUMP_1 : UINT;
  W_PUMP_2 : UINT;
  W_STATE_NO : UINT;
  W_LEAD_IS_2 : UINT;
  W_HIGH_ALARM : UINT;
  W_STATION_FAULT : UINT;
  W_COMMS_OK : UINT;
  W_SENSOR_FAULT : UINT;
END_VAR
  W_TOKEN := EPOCH;
  W_PUMP_1 := BOOL_TO_UINT(PUMP_1);
  W_PUMP_2 := BOOL_TO_UINT(PUMP_2);
  W_STATE_NO := INT_TO_UINT(STATE_NO);
  W_LEAD_IS_2 := BOOL_TO_UINT(LEAD_IS_2);
  W_HIGH_ALARM := BOOL_TO_UINT(HIGH_ALARM);
  W_STATION_FAULT := BOOL_TO_UINT(STATION_FAULT);
  W_COMMS_OK := BOOL_TO_UINT(COMMS_OK);
  W_SENSOR_FAULT := BOOL_TO_UINT(SENSOR_FAULT);
END_FUNCTION_BLOCK
