# Runbook

Untested in a live environment; commands assume the Kubernetes manifests in `infra/k8s`. Adapt names.

## Endpoints
`/healthz` liveness · `/readyz` readiness (DB, providers, kill switch; cheap) · `/metrics` Prometheus text (cluster-internal only) · `POST /v1/admin/audit/verify` full chain scan · `POST /v1/admin/sweep` SLA/orphan sweep (also run by CronJob) · `POST /v1/admin/kill-switch`.

## SLOs (proposed, not measured)
API p95 < 500 ms for reads; advance (async) accepted < 1 s; 99.5 % availability; audit chain verifies 100 %.
Alerts: `/readyz` failing > 2 min; 5xx > 2 %; circuit breaker open > 5 min; `vro_rate_limited_total` spike; job queue age > 15 min; audit verify failure (page immediately).

## Routine
- Start: apply migrations (`python -m vro.store --migrate` or the init job), then roll the Deployment.
- Stop: scale to 0; in-flight jobs are reaped as orphans on next start.
- Kill switch: `POST /v1/admin/kill-switch {"on": true}` (admin) stops agent runs; humans can still review.

## Incidents
**LLM provider outage / circuit open** — Symptom: degraded stats, `breaker open` errors. Action: system falls back to rules unless `LLM_ALLOW_FALLBACK=0`. Check provider status, key, quota. To force rules: set `LLM_PROVIDER=rules`, restart. Cases already in flight continue deterministically.

**Budget exceeded** — Agents stop with a budget error. Raise `LLM_BUDGET_*` only with approval, or switch to rules.

**Audit chain break (SEV1)** — `/v1/admin/audit/verify` returns a first bad seq. Freeze approvals (kill switch), snapshot the DB, do not "repair" rows. Compare with last backup and anchored head hash; open a security incident.

**Stuck/orphaned jobs** — jobs in RUNNING beyond `orphan_after_s` are marked FAILED by the sweep; re-trigger advance. Check pod restarts/OOM.

**DB failover / restore** — Postgres: promote replica, update `VRO_DATABASE_URL`, `/readyz` must pass, then run audit verify. PITR restore: restore to new instance, verify chain, switch over.

**Sanctions list update failure** — Screening continues against the previous list; stale list age is shown in status. Do not approve cases with list older than policy allows (pack rule).

**OIDC/JWKS outage** — Cached keys are used (stale-cache fallback); new key IDs fail closed (401). Fix IdP reachability; do not enable dev auth.

**PDF parser failures** — Spike in REJECTED: check worker timeout/memory settings, tesseract/poppler presence in image (`/readyz` reports OCR availability), and sample files. Never raise rlimits without review.

**Rate-limit false positives** — Raise `RATE_LIMIT_*`; behind a proxy set `TRUSTED_PROXIES` so client IPs are right.

## Backup / DR
Postgres PITR (RPO ≤ 5 min target), daily logical dump, test restore monthly; document store/object storage versioned. RTO target 1 h (unvalidated).
