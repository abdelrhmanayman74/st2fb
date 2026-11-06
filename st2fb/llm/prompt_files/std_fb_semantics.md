### R_TRIG
Inputs: CLK: BOOL. Outputs: Q: BOOL. State: M: BOOL.

```
Q := CLK AND NOT M;
M := CLK;
```

### F_TRIG
Inputs: CLK: BOOL. Outputs: Q: BOOL. State: M: BOOL.

```
Q := NOT CLK AND NOT M;
M := NOT CLK;
```

### SR
Inputs: S1: BOOL, R: BOOL. Outputs: Q1: BOOL. State: none.

```
Q1 := S1 OR (NOT R AND Q1);
```

### RS
Inputs: S: BOOL, R1: BOOL. Outputs: Q1: BOOL. State: none.

```
Q1 := NOT R1 AND (S OR Q1);
```

### CTU
Inputs: CU: BOOL, R: BOOL, PV: INT. Outputs: Q: BOOL, CV: INT. State: CU_T_Q: BOOL, CU_T_M: BOOL.

```
CU_T_Q := CU AND NOT CU_T_M;
CU_T_M := CU;
IF R THEN
  CV := 0;
ELSIF CU_T_Q AND (CV < PV) THEN
  CV := CV + 1;
END_IF;
Q := CV >= PV;
```

### CTD
Inputs: CD: BOOL, LD: BOOL, PV: INT. Outputs: Q: BOOL, CV: INT. State: CD_T_Q: BOOL, CD_T_M: BOOL.

```
CD_T_Q := CD AND NOT CD_T_M;
CD_T_M := CD;
IF LD THEN
  CV := PV;
ELSIF CD_T_Q AND (CV > 0) THEN
  CV := CV - 1;
END_IF;
Q := CV <= 0;
```

### TP
Inputs: IN: BOOL, PT: TIME. Outputs: Q: BOOL, ET: TIME. State: STATE: INT, PREV_IN: BOOL, START_TIME: TIME.

```
IF (STATE = 0) AND NOT PREV_IN AND IN THEN
  STATE := 1;
  Q := TRUE;
  START_TIME := CURRENT_TIME;
ELSIF STATE = 1 THEN
  IF START_TIME + PT <= CURRENT_TIME THEN
    STATE := 2;
    Q := FALSE;
    ET := PT;
  ELSE
    ET := CURRENT_TIME - START_TIME;
  END_IF;
END_IF;
IF (STATE = 2) AND NOT IN THEN
  ET := T#0s;
  STATE := 0;
END_IF;
PREV_IN := IN;
```

### TON
Inputs: IN: BOOL, PT: TIME. Outputs: Q: BOOL, ET: TIME. State: STATE: INT, PREV_IN: BOOL, START_TIME: TIME.

```
IF (STATE = 0) AND NOT PREV_IN AND IN THEN
  STATE := 1;
  Q := FALSE;
  START_TIME := CURRENT_TIME;
ELSE
  IF NOT IN THEN
    ET := T#0s;
    Q := FALSE;
    STATE := 0;
  ELSIF STATE = 1 THEN
    IF START_TIME + PT <= CURRENT_TIME THEN
      STATE := 2;
      Q := TRUE;
      ET := PT;
    ELSE
      ET := CURRENT_TIME - START_TIME;
    END_IF;
  END_IF;
END_IF;
PREV_IN := IN;
```

### TOF
Inputs: IN: BOOL, PT: TIME. Outputs: Q: BOOL, ET: TIME. State: STATE: INT, PREV_IN: BOOL, START_TIME: TIME.

```
IF (STATE = 0) AND PREV_IN AND NOT IN THEN
  STATE := 1;
  START_TIME := CURRENT_TIME;
ELSE
  IF IN THEN
    ET := T#0s;
    STATE := 0;
  ELSIF STATE = 1 THEN
    IF START_TIME + PT <= CURRENT_TIME THEN
      STATE := 2;
      ET := PT;
    ELSE
      ET := CURRENT_TIME - START_TIME;
    END_IF;
  END_IF;
END_IF;
Q := IN OR (STATE = 1);
PREV_IN := IN;
```
