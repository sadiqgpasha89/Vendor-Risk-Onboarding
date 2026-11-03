# ADR-0004: Offline rules provider is the default "LLM"
Status: accepted (deviation) - important caveat
Decision: The gateway has a deterministic rules provider so the full pipeline and evals run offline. A real provider plugs into the same gateway (budgets, kill switch, schema validation, PII scrub).
Consequences: Injection and verifier evals test structural defences (untrusted wrapping, no tools on A4, deterministic validators, quote checks), NOT model robustness. Re-run the evals against a real model before relying on them.
