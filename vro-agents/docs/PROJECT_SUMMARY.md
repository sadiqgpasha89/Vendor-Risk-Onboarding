# Build log and honest deviations

Built from `plan.md` (§14 task graph). Vertical slice first: intake -> screening -> tiering -> due diligence -> assessment -> independent verification -> human gates -> monitoring.

## What runs (verified here)
- 74 unit/integration tests (`make test`), ~9 s.
- Full evaluation suite with merge-gate thresholds (`make evals`), ~6 s.
- API (Starlette) + vanilla-JS UI + CLI; 14 synthetic scenarios end to end (`make demo`).
- Browser smoke test with Playwright/Chromium: no console errors.

## What was NOT exercised
Docker/Dockerfile, docker-compose, GitHub Actions, Postgres, pgvector, Temporal, MCP servers, Next.js, Helm/Terraform, real LLM provider, PDF/OCR parsing, OIDC, rate limiting, load/perf testing.

## Deviations from plan
| Plan | Built | Why |
|---|---|---|
| FastAPI | Starlette | pip blocked; FastAPI not installed |
| Next.js UI | Vanilla JS SPA | npm blocked |
| Postgres + pgvector | SQLite + hashing embedder | ADR-0001 |
| MCP | In-process registry | ADR-0002 |
| Temporal | State machine | ADR-0003 |
| LLM | Rules provider | ADR-0004 |
| pytest | unittest | pip blocked |
| §15.2 residual | + high-finding floor | ADR-0006 |

## Eval results (last full run)
Sanctions recall 1.0 (592 cases), citation validity 1.0, tier agreement 1.0, injection ASR 0/12, verifier false-trust 0.0 (865 trials), staleness/drift/boundary/replay pass. These are synthetic, self-built sets; see ADR-0004/0005. Retrieval hit@3 0.875 is informational and not discriminating at this corpus size.

## Other caveats
Regulatory references are marked VERIFY. Policy thresholds are illustrative defaults, not a bank's risk appetite.


---
# README
# vro-agents - Vendor Risk Onboarding (multi-agent, BFSI)

Reference implementation of a human-in-the-loop, evidence-first vendor / third-party risk onboarding system. **Synthetic data only.** Not a compliance product; see `docs/BUILD_LOG.md` for what is and isn't verified.

## Principles
LLMs propose, deterministic code disposes - agents never approve, reject, clear sanctions or send. Every claim carries evidence (doc, page, <=40-word quote, sha256). Vendor documents are untrusted data; the Reader agent has no tools. Segregation of duties, open-CRITICAL blocks, and tier-based approvers are enforced in code. The audit log is hash-chained and append-only.

## Flow
NEW -> INTAKE_REVIEW (G0) -> SCREENING (G1 per match) -> TIERING (G2 for T1/T2) -> DUE_DILIGENCE -> ASSESSMENT -> VERIFICATION -> HUMAN_REVIEW (G3) -> CONTRACTING -> FINAL_APPROVAL (G4) -> ONBOARDED -> MONITORING. Also ON_HOLD, REJECTED, OFFBOARDING.

Agents: A1 intake, A2 screening, A3 tiering, A4 reader, A5-A8 specialists, A9 synthesizer, A10 independent verifier, A11 steward, A12 comms drafter; A0 orchestrator = `vro/workflow.py`.

## Run
```
make synth      # deterministic synthetic vendors + sanctions list
make test       # 74 tests
make evals      # merge-gating evaluation suite
make demo       # all 14 scenarios via CLI
make run        # API + UI at http://localhost:8000
```
UI: open `/`, pick a role (sponsor, analyst, senior_risk, aml, manager, committee, head_tprm), load a synthetic scenario, and drive the case through the gates. Dev auth token: `Authorization: Bearer dev.<user>.<role>`.

CLI: `python -m vro.cli {new-case,upload,show,list,decide,packet,verify-audit,sweep,demo,serve}`.

## Layout
`vro/` core (policy, scoring, screening, docproc, retrieval, ledger, gateway, workflow, api, cli) - `vro/agents/` agents - `policy/packs/` policy-as-data - `ui/` SPA - `tools/synth` generator - `evals/` harness + thresholds - `contracts/` JSON Schemas (`make contracts`) - `docs/adr/` decisions.

## Before production
Port to Postgres/pgvector, Temporal, MCP; add OIDC, rate limiting, PDF/OCR ingestion; plug a real LLM provider and re-run the evals; have compliance verify every regulatory reference and the risk owner sign off scoring thresholds (ADR-0006).

## Second pass (live LLM, Postgres, PDF/OCR, hardening)
- Live LLM: `vro/llm_backends.py`, `vro/llm_live.py`, `evals/live.py`, `.env.example`, `docs/LIVE_LLM.md`. Verified only with a scripted fake model; real-model scores unknown.
- Postgres/pgvector/RLS: `vro/store_pg.py`, `migrations/postgres/`, `tools/migrate_sqlite_to_pg.py`, `docs/POSTGRES.md`. Not run against a live database.
- PDF/OCR: sandboxed `vro/pdfworker.py` + `vro/pdfparse.py`; tested with generated PDFs and tesseract; not with real vendor reports.
- Hardening: OIDC, rate limits, async jobs, per-case locks, circuit breaker, metrics, JSON logs; `docs/THREAT_MODEL.md`, `RUNBOOK.md`, `SECURITY.md`, `ARCHITECTURE.md`, ADRs 0008-0014; k8s/compose/Dockerfile/CI (unrun).
- Tests: 168 (7 gated Postgres tests skipped). `make ci` passes.
