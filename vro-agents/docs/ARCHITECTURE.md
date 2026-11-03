# Architecture and scaling

```
Client/UI -> Ingress -> API replicas (Starlette, stateless)
   API -> Postgres (+pgvector, FTS, RLS)      state, audit chain, retrieval
   API -> Job runner (in-process threads)     async advance, per-case advisory locks
   API -> LLM gateway -> provider backend     breaker, budgets, redaction, fallback to rules
   API -> PDF worker (sandboxed subprocess)   text, hidden text, OCR
   API -> Redis (optional)                    shared rate limits
   CronJob -> /v1/admin/sweep                 SLAs, orphans, chain verify
```

**Why these choices.** Stateless API + DB-held state lets replicas scale horizontally; per-case advisory locks give correctness without sticky sessions; the deterministic core means LLM latency never gates safety. See ADRs 0001-0014.

**Scaling plan.** (1) Replicas behind HPA on CPU/p95. (2) Move jobs to a durable queue/Temporal when job volume or duration exceeds in-process capacity (ADR-0003). (3) Move OCR to a separate worker pool. (4) Read replicas for search. (5) Partition `audit_log` and `doc_chunks` by tenant/time.

**Capacity (rough estimates, unmeasured).** A case ≈ 5-15 documents, 200-2000 chunks, ~30 LLM calls. 1,000 cases/day ≈ 0.7 cases/min average; a handful of replicas and a small Postgres suffice; LLM cost/latency dominates, OCR CPU second. Measure with your data before sizing.

**Failure modes.** LLM down → rules fallback; DB down → readyz fails, no writes; Redis down → fall back to local limiter; IdP down → cached JWKS.

**Known limits.** Multi-column PDF reading order, header/footer stripping, English-only OCR by default, OCR runs inside the upload request, per-replica limiter without Redis.
