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


## Second pass: live LLM, Postgres, PDF/OCR, production hardening
Start with `docs/LIVE_LLM.md` (Ollama or Google key via `.env`, then `python -m evals.live`), `docs/POSTGRES.md`, `docs/SECURITY.md`, `docs/THREAT_MODEL.md`, `docs/RUNBOOK.md`, `docs/ARCHITECTURE.md`. Infra (unrun): `Dockerfile`, `infra/compose`, `infra/k8s`, `.github/workflows/ci.yml`.
PDF ingestion needs `pip install -e ".[dev]"` (or `[prod]`) plus system `tesseract-ocr` and `poppler-utils` for OCR. See `docs/BUILD_LOG.md` for exactly what was and was not verified.
