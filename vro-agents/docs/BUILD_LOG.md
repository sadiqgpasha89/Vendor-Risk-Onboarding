# Build log and honest deviations

Built from `plan.md` (§14 task graph). Vertical slice first: intake -> screening -> tiering -> due diligence -> assessment -> independent verification -> human gates -> monitoring.

## What runs (verified here)
- 168 unit/integration tests (`make test`; 7 Postgres tests skip without `VRO_TEST_DATABASE_URL`).
- Full evaluation suite with merge-gate thresholds (`make evals`), ~6 s.
- API (Starlette) + vanilla-JS UI + CLI; 14 synthetic scenarios end to end (`make demo`).
- Browser smoke test with Playwright/Chromium: no console errors.

## What was NOT exercised
Docker/Dockerfile, docker-compose, Kubernetes manifests, GitHub Actions, Temporal, MCP servers, Next.js, Terraform, load/perf testing.

### Written in the second pass, with how far each was verified
| Area | Verified here | NOT verified |
|---|---|---|
| Live LLM (Ollama/Google/OpenAI-compat/Anthropic backends, evals) | Whole path against a scripted fake model (`make evals-live-dry`); prompt/parse hardening tests | Any real model; real-model scores, cost, latency |
| Postgres + pgvector + RLS + migration tool | SQL translation, helpers, schema parity vs SQLite | Everything that needs a live Postgres (set `VRO_TEST_DATABASE_URL` to run the gated tests), RLS, HNSW, the migration tool |
| PDF + OCR | Real PDFs generated in tests: text, hidden text, JS/attachments, encrypted, corrupt, timeout, memory limit, scans via tesseract | Real vendor SOC 2 PDFs (layouts vary), multi-column order, non-English OCR |
| OIDC / rate limiting / jobs / locks / breaker / metrics / logging | Unit tests incl. local RSA keys, event-loop non-blocking test | A real IdP, Redis limiter, OTLP exporter, multi-replica behaviour |
| Docs / infra (threat model, runbook, security, k8s, CI) | YAML/TOML parse only | Applying/building/running any of it |

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
