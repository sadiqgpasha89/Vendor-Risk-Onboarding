# Running the evals against a real LLM

Not run by the authors (no model access). Copy `.env.example` to `.env`.

Ollama: `LLM_PROVIDER=ollama`, `LLM_MODEL=qwen2.5:14b` (any pulled model), optional `OLLAMA_BASE_URL`.
Google: `LLM_PROVIDER=google`, `GOOGLE_API_KEY=...`, `LLM_MODEL=gemini-2.5-flash` (check current id).

```
python -m evals.live --backend ollama --quick          # smoke
python -m evals.live --backend google --yes            # hosted: needs --yes
make evals-live-dry                                    # scripted backend, no model
```
Gates: `evals/thresholds_live.yaml` (safety strict; rule agreement >= 0.85; verifier accuracy >= 0.90). Use `--mode record/replay --cassette f.json` to freeze responses. Report: `evals/live_report.json` including tokens, cost, latency, degraded-output counts. Set `LLM_ALLOW_FALLBACK=0` so failures are not hidden by the rules fallback. Hosted runs send synthetic data only; do not point at real vendor files without approval.
