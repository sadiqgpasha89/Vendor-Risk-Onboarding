"""Run the evaluation suites against a REAL model (Ollama, Google Gemini, any OpenAI-compatible server, or Anthropic).

    cp .env.example .env            # set LLM_PROVIDER and (for hosted providers) LLM_API_KEY
    python -m evals.live --quick --yes                       # smoke run, ~9 scenarios
    python -m evals.live --yes --out evals/live_report.json  # full run
    python -m evals.live --backend scripted                  # no model: checks the plumbing only

What it adds over `python -m evals.runner`:
  * the agents run on the model via LiveProvider (vro/llm_live.py); safety checks stay deterministic;
  * a behavioural diff against the offline rules baseline (tier/band/rules/state per scenario);
  * cost, token, latency, retry, degraded-output counters;
  * record/replay cassettes (--cassette file --mode record|replay) so a good run can be re-checked in CI without the model;
  * stricter thresholds for safety, relaxed for capability (evals/thresholds_live.yaml).
Sanctions matching, scoring and staleness never call a model, so they are skipped here (run `make evals` for them).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from vro.agents.services import Services
from vro.config import Settings
from vro.llm_gateway import Gateway
from vro.util import set_now

from . import runner

PAID = {"google", "openai", "anthropic"}


def build_factory(a, created: list):
    def factory(pack: str) -> Services:
        s = Settings(db_path=":memory:", policy_pack=pack, llm_provider="ollama" if a.backend == "scripted" else a.backend)
        if a.model:
            s.llm_model_small = s.llm_model_mid = s.llm_model_large = a.model
        if a.base_url:
            s.llm_base_url = a.base_url
        s.llm_allow_fallback = False
        if a.backend == "scripted":
            from vro.llm_live import LiveProvider
            from .scripted_backend import ScriptedBackend
            gw = Gateway(s, providers=[LiveProvider(ScriptedBackend(), s)])
        else:
            gw = Gateway(s, cassette=a.cassette, cassette_mode=a.mode)
        svc = Services(s, gateway=gw)
        created.append(svc)
        return svc
    return factory


def totals(created: list) -> dict:
    t = {"calls": 0, "retries": 0, "cache_hits": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "latency_s": 0.0, "degraded": 0, "json_repairs": 0,
         "by_task": {}}
    for svc in created:
        st = svc.gateway.stats
        for k in ("calls", "retries", "cache_hits", "tokens_in", "tokens_out", "cost_usd", "latency_s"):
            t[k] += st[k]
        for k, v in st["by_task"].items():
            t["by_task"][k] = t["by_task"].get(k, 0) + v
        for p in svc.gateway.providers:
            for k in ("degraded", "json_repairs"):
                t[k] += getattr(p, "stats", {}).get(k, 0)
    t["cost_usd"] = round(t["cost_usd"], 4)
    t["latency_s"] = round(t["latency_s"], 1)
    return t


def baseline_diff(live_runs: dict, quick: bool, pack: str) -> list[dict]:
    runner.SERVICE_FACTORY = None
    _, base = runner.scenario_suite(pack, quick)
    out = []
    for k, (_, lr) in live_runs.items():
        br = base[k][1]
        diff = {f: (br.get(f), lr.get(f)) for f in ("state", "proposed_tier", "band") if br.get(f) != lr.get(f)}
        rb, rl = set(br.get("rules") or []), set(lr.get("rules") or [])
        if rb != rl:
            diff["rules_missing_vs_baseline"] = sorted(rb - rl)
            diff["rules_extra_vs_baseline"] = sorted(rl - rb)
        out.append({"scenario": k, "identical_to_baseline": not diff, **({"diff": diff} if diff else {})})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default=None, help="ollama|google|openai|anthropic|scripted (default: LLM_PROVIDER from .env)")
    ap.add_argument("--model", help="override all three model tiers")
    ap.add_argument("--base-url")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--pack", default="default")
    ap.add_argument("--max-verifier-trials", type=int, default=120)
    ap.add_argument("--cassette")
    ap.add_argument("--mode", default="off", choices=["off", "record", "replay"])
    ap.add_argument("--out", default="evals/live_report.json")
    ap.add_argument("--yes", action="store_true", help="confirm you accept calls (and cost) on a hosted provider")
    a = ap.parse_args(argv)
    a.backend = a.backend or Settings().llm_provider
    if a.backend == "rules":
        print("LLM_PROVIDER is 'rules'. Set LLM_PROVIDER in .env (ollama|google|openai|anthropic) or pass --backend.", file=sys.stderr)
        return 2
    if a.backend in PAID and not a.yes and a.mode != "replay":
        print(f"{a.backend} is a hosted provider: this run makes hundreds of paid calls. Re-run with --yes to confirm.", file=sys.stderr)
        return 2
    created: list = []
    runner.SERVICE_FACTORY = build_factory(a, created)
    runner.VERIFIER_TRIAL_LIMIT = a.max_verifier_trials
    t0 = time.time()
    import yaml
    th = yaml.safe_load((runner.ROOT / "thresholds_live.yaml").read_text())
    m: dict = {}
    sm, runs = runner.scenario_suite(a.pack, a.quick)
    m.update(sm)
    m.update(runner.injection_suite(a.pack, a.quick))
    m.update(runner.verifier_suite(runs))
    m.update(runner.boundary_suite(runs, a.pack))
    diff = baseline_diff(runs, a.quick, a.pack)
    runner.SERVICE_FACTORY = None
    set_now(None)
    fails = runner.check(th, m)
    s0 = Settings(llm_provider=a.backend if a.backend != "scripted" else "ollama")
    rep = {"passed": not fails, "failures": fails, "metrics": m, "baseline_diff": diff, "usage": totals(created), "seconds": round(time.time() - t0, 1),
           "provider": a.backend, "models": {"small": a.model or s0.llm_model_small, "mid": a.model or s0.llm_model_mid, "large": a.model or s0.llm_model_large},
           "quick": a.quick, "note": "scripted backend is not a model" if a.backend == "scripted" else ""}
    Path(a.out).write_text(json.dumps(rep, indent=1, default=str))
    show = {k: v for k, v in m.items() if not isinstance(v, (list, dict))}
    print(json.dumps({"passed": rep["passed"], "failures": fails, "metrics": show, "usage": rep["usage"], "seconds": rep["seconds"]}, indent=1, default=str))
    print("\nbehavioural diff vs rules baseline:")
    for d in diff:
        print(" ", "=" if d["identical_to_baseline"] else "!", d["scenario"], d.get("diff", ""))
    print(f"\nfull report: {a.out}")
    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
