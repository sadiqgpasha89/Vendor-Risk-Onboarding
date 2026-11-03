# ADR-0006: High-finding floor on the residual band (extension to plan 15.2)
Status: proposed - needs risk-owner sign-off
Context: With the plan's formula, strong controls in other domains could average away an open HIGH finding and yield a LOW band.
Decision: Policy-as-data `high_finding_floor: {one_band: MEDIUM, many_count: 3, many_band: HIGH}` in `scoring.yaml`. One open HIGH finding => at least MEDIUM; three or more => at least HIGH. The existing CRITICAL floor is unchanged. `critical_cap_applied` flags when a floor fires.
Consequences: Deviates from the spec; thresholds are tunable per pack and changes go through 4-eyes + eval gate.
