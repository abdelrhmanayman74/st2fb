(* From Intecre/twincat-utils, FB_AlphaBetaFilter. Copyright (c) 2022 Intecre Ltd. MIT licence, see LICENSE in this directory. *)
(* https://en.wikipedia.org/wiki/Alpha_beta_filter *)
FUNCTION_BLOCK FB_AlphaBetaFilter
VAR_INPUT
   measurement : REAL; (* raw value to filter *)
   deltaInSecond : REAL; (* time between this and last cycle MAKE SURE > 0! *)
   alpha : REAL; (* alpha value. 0 - 1.0  *)
   beta : REAL; (* beta value. Use something low (0.001 < beta < 0.1) *)
END_VAR
VAR_OUTPUT
   output : REAL; (* filtered output *)
END_VAR
VAR
   measurementEstimate, velocityEstimate : REAL := 0.0;
   predictionError, measurementIntegrator, velocityIntegrator : REAL; (* overwritten each scan. *)
   betaResidualByDelta : REAL; (* used to simplify code, protecting div by zero issues. *)
END_VAR
measurementIntegrator := measurementEstimate + (velocityEstimate * deltaInSecond);
velocityIntegrator := velocityEstimate;

predictionError := measurement - measurementIntegrator;

measurementIntegrator :=
   measurementIntegrator + (alpha * predictionError);

(* div by zero protection for below *)
betaResidualByDelta :=
   SEL(deltaInSecond > 0.0, 0.0, (beta * predictionError) / deltaInSecond);

velocityIntegrator := velocityIntegrator + betaResidualByDelta;

measurementEstimate := measurementIntegrator;
velocityEstimate := velocityIntegrator;

output := measurementEstimate;
END_FUNCTION_BLOCK
