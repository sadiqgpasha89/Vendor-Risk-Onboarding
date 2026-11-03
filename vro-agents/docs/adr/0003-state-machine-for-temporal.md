# ADR-0003: Explicit state machine stands in for Temporal
Status: accepted (deviation)
Decision: `vro/workflow.py` persists case state and gate tasks; every step is idempotent (sha key over case|agent|prompt|policy|input) and replayable (R6).
Consequences: No durable timers or worker fleet. Porting to Temporal means wrapping `_st_*` handlers as activities.
