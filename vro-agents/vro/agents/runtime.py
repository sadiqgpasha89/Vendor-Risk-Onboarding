"""Agent runtime: idempotent, audited agent runs (R6) and persistence of validated agent results (R2, GR-004)."""
from __future__ import annotations

import time
from typing import Any, Callable

from ..llm_gateway import BudgetExceeded, GatewayError, KillSwitchActive
from ..models import AgentResult
from ..util import canonical_json, iso, new_id, now, sha256_text
from ..validators import validate_result
from .prompts import PROMPT_VERSION
from .services import Services


class AgentFailure(Exception):
    pass


def run_agent(svc: Services, case: dict, agent: str, input_obj: Any, fn: Callable[[str], dict], *, trace_id: str | None = None) -> dict:
    """Run fn(run_id)->dict once per (case, agent, prompt, policy, input). A repeat returns the stored output (replayable)."""
    in_hash = sha256_text(canonical_json(input_obj))
    key = sha256_text(f"{case['case_id']}|{agent}|{PROMPT_VERSION}|{svc.policy.version}|{in_hash}")
    prior = svc.store.one("SELECT * FROM agent_runs WHERE idempotency_key=?", (key,))
    if prior and prior["status"] == "OK":
        return prior["output"] or {}
    if prior:      # failed earlier: retry with the same key by removing the failed record (audit keeps the history)
        svc.store.execute("DELETE FROM agent_runs WHERE idempotency_key=?", (key,))
    run_id = new_id("run_")
    t0 = time.time()
    svc.store.insert("agent_runs", {"run_id": run_id, "tenant_id": case["tenant_id"], "case_id": case["case_id"], "agent": agent,
                                    "model": svc.gateway.model_for("mid"), "prompt_version": PROMPT_VERSION, "status": "RUNNING",
                                    "idempotency_key": key, "input_hash": in_hash, "trace_id": trace_id, "started_at": iso(now())})
    try:
        out = fn(run_id)
        status = "OK"
    except (KillSwitchActive, BudgetExceeded) as e:
        svc.store.update("agent_runs", "run_id", run_id, {"status": "BLOCKED", "output": {"error": str(e)}})
        svc.store.audit(case["tenant_id"], agent, "agent", "AGENT_BLOCKED", "case", case["case_id"], {"reason": str(e)})
        raise
    except (GatewayError, Exception) as e:
        svc.store.update("agent_runs", "run_id", run_id, {"status": "ERROR", "output": {"error": f"{type(e).__name__}: {e}"[:500]},
                                                          "latency_ms": int((time.time() - t0) * 1000)})
        svc.store.audit(case["tenant_id"], agent, "agent", "AGENT_ERROR", "case", case["case_id"], {"error": f"{type(e).__name__}: {e}"[:300]})
        raise
    svc.store.update("agent_runs", "run_id", run_id, {"status": status, "output": out, "latency_ms": int((time.time() - t0) * 1000)})
    svc.store.audit(case["tenant_id"], agent, "agent", "AGENT_RUN", "case", case["case_id"], {"run_id": run_id, "status": status})
    return out


def persist_result(svc: Services, case: dict, agent: str, result: AgentResult) -> dict:
    """Validate (grounding, language safety), then write claims as UNTRUSTED, findings and questions. Returns counts + claim ids."""
    rep = validate_result(svc.store, case["tenant_id"], case["vendor_id"], result)
    ids = []
    for c in rep.result.claims:
        ids.append(svc.ledger.create_claim(case["tenant_id"], case["vendor_id"], case["case_id"], c, f"{agent}", PROMPT_VERSION))
    for q in rep.result.questions:
        svc.store.insert("questions", {"question_id": new_id("q_"), "tenant_id": case["tenant_id"], "case_id": case["case_id"],
                                       "to_role": q.to_role, "text": q.text, "why": q.why_it_matters, "blocking": q.blocking,
                                       "options": q.options, "status": "OPEN", "created_at": iso(now())})
    if rep.dropped:
        svc.store.audit(case["tenant_id"], agent, "agent", "CLAIMS_DROPPED", "case", case["case_id"], {"dropped": rep.dropped[:10]})
    return {"claim_ids": ids, "dropped": rep.dropped, "rewritten": rep.rewritten, "questions": len(rep.result.questions)}
