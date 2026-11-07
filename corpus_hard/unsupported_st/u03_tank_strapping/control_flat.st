(* Solvability control, never shown to a model: the same behaviour in the translator's v1 subset. The table became
   a chain of IFs, and RETURN became an enclosing IF. *)
FUNCTION_BLOCK TANK_STRAPPING
VAR_INPUT
  LEVEL_MM : REAL;
  DENSITY : REAL;
  HOLD : BOOL;
END_VAR
VAR_OUTPUT
  VOLUME_L : REAL;
  MASS_KG : DINT;
  SEGMENT : INT;
  OUT_OF_RANGE : BOOL;
END_VAR
VAR
  L0, L1, V0, V1 : REAL;
  FRACTION : REAL;
END_VAR
  IF NOT HOLD THEN
    OUT_OF_RANGE := (LEVEL_MM < 0.0) OR (LEVEL_MM > 2000.0);
    IF LEVEL_MM <= 200.0 THEN
      SEGMENT := 0;
      L0 := 0.0;
      L1 := 200.0;
      V0 := 0.0;
      V1 := 150.0;
    ELSIF LEVEL_MM <= 400.0 THEN
      SEGMENT := 1;
      L0 := 200.0;
      L1 := 400.0;
      V0 := 150.0;
      V1 := 340.0;
    ELSIF LEVEL_MM <= 800.0 THEN
      SEGMENT := 2;
      L0 := 400.0;
      L1 := 800.0;
      V0 := 340.0;
      V1 := 800.0;
    ELSIF LEVEL_MM <= 1200.0 THEN
      SEGMENT := 3;
      L0 := 800.0;
      L1 := 1200.0;
      V0 := 800.0;
      V1 := 1350.0;
    ELSE
      SEGMENT := 4;
      L0 := 1200.0;
      L1 := 2000.0;
      V0 := 1350.0;
      V1 := 2600.0;
    END_IF;
    FRACTION := (LEVEL_MM - L0) / (L1 - L0);
    FRACTION := LIMIT(0.0, FRACTION, 1.0);
    VOLUME_L := V0 + FRACTION * (V1 - V0);
    MASS_KG := REAL_TO_DINT(VOLUME_L * DENSITY);
  END_IF;
END_FUNCTION_BLOCK
