"""HTTP API (Starlette ASGI). Thin layer: authN/authZ, validation, idempotency, error mapping. All rules live in Workflow/PolicyEngine.

Dev auth: `Authorization: Bearer dev.<user>.<role>[.<tenant>]` (VRO_DEV_AUTH=1). Production must put OIDC in front (plan §8.4).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from collections import Counter
from pathlib import Path

import anyio
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import packet as packet_mod
from .agents import screening_agent
from .agents.services import Services
from .config import ROOT, Settings
from .llm_gateway import BudgetExceeded, GatewayError, KillSwitchActive
from .jobs import JobRunner
from .models import GateDecision
from .obs import Histogram, init_tracing, log, setup_logging, span
from .security import AuthError, OidcVerifier, RateLimiter, make_limiter, production_problems
from .policy import PolicyError
from .screening import SanctionsList
from .util import canonical_json, iso, new_id, now, sha256_text
from .workflow import Actor, NotFound, Workflow

METRICS: Counter = Counter()
MAX_BODY = 40_000_000


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


def jerr(status: int, code: str, message: str, trace: str = "", headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "trace_id": trace}}, status_code=status, headers=headers)


LATENCY = Histogram()
_ID_SEG = re.compile(r"/[a-z]{1,5}_[0-9a-f]{8,}")
RATE_LIMITED: Counter = Counter()


class Ctx:
    """Per-app singletons so tests can build isolated apps."""
    def __init__(self, svc: Services):
        self.svc, self.wf = svc, Workflow(svc)


def client_ip(request: Request, trusted_hops: int) -> str:
    if trusted_hops > 0:
        xff = [x.strip() for x in request.headers.get("x-forwarded-for", "").split(",") if x.strip()]
        if len(xff) >= trusted_hops:
            return xff[-trusted_hops]                    # the address the outermost TRUSTED proxy saw; anything left of it is client-controlled
    return request.client.host if request.client else "unknown"


class Auth:
    """Resolves the caller (dev token or OIDC JWT), applies per-principal rate limits and scopes the DB session to the caller's tenant."""
    def __init__(self, svc: Services):
        self.svc, s = svc, svc.settings
        self.oidc = OidcVerifier.from_settings(s)
        self.limiter = make_limiter(s)
        self.fail_limiter = RateLimiter()

    @staticmethod
    def _limit_class(request: Request) -> str:
        if request.method in ("GET", "HEAD"):
            return "read"
        return "upload" if request.url.path.endswith("/documents") or "/webhooks/" in request.url.path else "write"

    def _unauth(self, request: Request, reason: str, status: int = 401):
        METRICS[("auth", "failed")] += 1
        ok, retry = self.fail_limiter.hit("ip:" + client_ip(request, self.svc.settings.trusted_proxies), self.svc.settings.rate_limit_auth_fail_rpm)
        if not ok:
            RATE_LIMITED["auth_fail"] += 1
            raise ApiError(429, "E_RATE", "too many failed authentication attempts", {"Retry-After": str(int(retry) + 1)})
        log("auth_failed", logging.WARNING, reason=reason, path=request.url.path)          # reason is for operators; the client sees a generic message
        raise ApiError(status, "E_AUTH", "missing or invalid credentials" if status == 401 else "access denied")

    def actor(self, request: Request) -> Actor:
        s, svc = self.svc.settings, self.svc
        h = request.headers.get("authorization", "")
        if not h.lower().startswith("bearer "):
            self._unauth(request, "no bearer token")
        tok = h[7:].strip()
        if s.dev_auth and tok.startswith("dev."):
            parts = tok[4:].split(".")
            if len(parts) < 2 or not parts[0] or parts[1] not in svc.policy.gates["roles"]:
                self._unauth(request, "bad dev token")
            actor = Actor(parts[0], parts[1], parts[2] if len(parts) > 2 else "t_demo")
        elif self.oidc:
            try:
                pr = self.oidc.verify(tok)
            except AuthError as e:
                self._unauth(request, e.reason, e.status)
            known = [r for r in pr.roles if r in svc.policy.gates["roles"]]
            want = request.headers.get("x-vro-role")
            if want:
                if want not in known:
                    self._unauth(request, f"role {want!r} not granted to {pr.user_id}", 403)
                role = want
            elif len(known) == 1:
                role = known[0]
            elif not known:
                self._unauth(request, "no recognised role", 403)
            else:
                raise ApiError(400, "E_ROLE_AMBIGUOUS", "you hold several roles; choose one with the X-VRO-Role header")
            actor = Actor(pr.user_id, role, pr.tenant_id)
        else:
            self._unauth(request, "no authenticator accepts this token")
        cls = self._limit_class(request)
        limit = {"read": s.rate_limit_rpm, "write": s.rate_limit_write_rpm, "upload": s.rate_limit_upload_rpm}[cls]
        ok, retry = self.limiter.hit(f"{actor.tenant_id}:{actor.user_id}:{cls}", limit)
        if not ok:
            RATE_LIMITED[cls] += 1
            raise ApiError(429, "E_RATE", "rate limit exceeded", {"Retry-After": str(int(retry) + 1)})
        svc.store.set_tenant(actor.tenant_id)             # row-level security scope for this request (no-op on SQLite)
        request.state.actor = actor
        return actor


def actor_of(request: Request, svc: Services) -> Actor:
    return svc.auth.actor(request)


def need(actor: Actor, svc: Services, perm: str) -> None:
    if not svc.policy.role_can(actor.role, perm):
        raise ApiError(403, "E_ROLE", f"role '{actor.role}' lacks permission '{perm}'")


def raw_body(request: Request) -> bytes:
    return getattr(request.state, "raw", b"")


def body_json(request: Request) -> dict:
    raw = raw_body(request)
    if len(raw) > MAX_BODY:
        raise ApiError(413, "E_SIZE", "request body too large")
    try:
        d = json.loads(raw or b"{}")
    except ValueError:
        raise ApiError(400, "E_JSON", "invalid JSON body")
    if not isinstance(d, dict):
        raise ApiError(400, "E_JSON", "JSON object expected")
    return d


def offload(fn):
    """Run a blocking handler in a worker thread so database and model calls never stall the event loop (health checks, other users)."""
    async def endpoint(request: Request):
        if request.method in ("POST", "PUT", "PATCH"):
            request.state.raw = await request.body()
        return await anyio.to_thread.run_sync(fn, request)
    endpoint.__name__ = getattr(fn, "__name__", "endpoint")
    return endpoint


def build_app(svc: Services | None = None) -> Starlette:
    svc = svc or Services()
    C = Ctx(svc)
    st, wf = svc.store, C.wf
    svc.auth = Auth(svc)
    jobs = JobRunner(st, svc.settings.job_workers)
    svc.jobs = jobs

    def idem(request: Request, actor: Actor):
        k = request.headers.get("idempotency-key")
        if not k:
            return None, None
        key = f"{actor.tenant_id}:{request.method}:{request.url.path}:{k}"
        row = st.get("idempotency", "key", key)
        return key, (row["response"] if row else None)

    def remember(key, resp: dict, actor: Actor):
        if key:
            st.insert("idempotency", {"key": key, "tenant_id": actor.tenant_id, "response": resp, "created_at": iso(now())})

    def case_view(case_id: str, actor: Actor) -> dict:
        c = wf._scoped(case_id, actor)
        q = st.query
        tasks = q("SELECT * FROM gate_tasks WHERE case_id=? ORDER BY created_at", (case_id,))
        a = st.one("SELECT * FROM assessments WHERE case_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (case_id,))
        timeline = q("SELECT seq, ts, actor, actor_type, action, payload FROM audit_events WHERE entity_id=? OR (entity_type='document' AND payload LIKE ?) ORDER BY seq",
                     (case_id, f'%{c["vendor_id"]}%'))
        docs = q("SELECT doc_id, doc_type, filename, sha256, quarantine_status, hidden_text_flag, injection_flags, page_count, uploaded_by, uploaded_at, supersedes_doc_id, processed "
                 "FROM documents WHERE vendor_id=? ORDER BY uploaded_at", (c["vendor_id"],))
        plan = svc.case_plan(case_id)
        return {
            "case": {k: c[k] for k in ("case_id", "tenant_id", "vendor_id", "requester_id", "preparer_id", "state", "proposed_tier", "final_tier", "emergency",
                                       "hold_reason", "conditional_expires", "created_at", "updated_at", "jurisdictions", "intake", "context")},
            "tasks": tasks, "assessment": a, "documents": docs,
            "missing_docs": wf.missing_docs(c) if c["state"] not in ("NEW",) else [],
            "plan": plan, "screening": q("SELECT * FROM screening_results WHERE case_id=? ORDER BY score DESC", (case_id,)),
            "findings": q("SELECT * FROM findings WHERE case_id=? AND status='OPEN' ORDER BY CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 WHEN 'LOW' THEN 3 ELSE 4 END", (case_id,)),
            "questions": q("SELECT * FROM questions WHERE case_id=? ORDER BY created_at", (case_id,)),
            "drafts": q("SELECT * FROM drafts WHERE case_id=? ORDER BY created_at", (case_id,)),
            "approvals": q("SELECT * FROM approvals WHERE case_id=? ORDER BY decided_at", (case_id,)),
            "claim_counts": {r["status"]: r["n"] for r in q("SELECT status, COUNT(*) n FROM claims WHERE vendor_id=? GROUP BY status", (c["vendor_id"],))},
            "open_critical": wf.open_criticals(case_id), "timeline": timeline,
            "allowed_gate_roles": {g: svc.policy.gate_roles(g, c["final_tier"] or c["proposed_tier"]) for g in ("G0", "G1", "G2", "G3", "G4", "GX")},
        }

    # ---------------------------------------------------------------- handlers
    async def healthz(request):
        return JSONResponse({"status": "ok"})

    def readyz(request):
        """Readiness = can this replica do useful work? Cheap checks only; the O(n) audit-chain scan runs in /v1/admin/audit/verify and the sweep."""
        try:
            st.one("SELECT 1 x")
        except Exception as e:  # noqa: BLE001
            log("not_ready", logging.ERROR, error=type(e).__name__)
            return jerr(503, "E_NOT_READY", "database unavailable")
        verified = st.get("flags", "name", "audit_chain_ok")
        open_breakers = [getattr(p, "name", str(i)) for i, (p, b) in enumerate(zip(svc.gateway.providers, svc.gateway.breakers)) if b.state == "open"]
        return JSONResponse({"status": "ready", "policy_version": svc.policy.version, "llm_provider": svc.settings.llm_provider,
                             "kill_switch": st.flag("kill_switch") == "1", "llm_circuit_open": open_breakers,
                             "audit_chain_ok": None if not verified else verified["value"] == "1", "audit_verified_at": verified and verified["updated_at"]})

    def metrics(request):
        """Prometheus text format. Expose only on the cluster network (NetworkPolicy / ingress rule), never publicly."""
        L = ["# TYPE vro_http_requests_total counter"]
        for k, n in sorted(METRICS.items(), key=lambda kv: str(kv[0])):
            if len(k) == 2 and isinstance(k[1], int):
                L.append(f'vro_http_requests_total{{method="{k[0]}",status="{k[1]}"}} {n}')
        L += ["# TYPE vro_rate_limited_total counter"] + [f'vro_rate_limited_total{{class="{c}"}} {n}' for c, n in sorted(RATE_LIMITED.items())]
        L += [f'vro_auth_failures_total {METRICS[("auth", "failed")]}', f'vro_webhook_bad_signature_total {METRICS[("webhook", "bad_sig")]}']
        L += LATENCY.render("vro_http_request_seconds", ("method", "route"))
        L.append("# TYPE vro_cases gauge")
        for r in st.query("SELECT state, COUNT(*) n FROM cases GROUP BY state"):
            L.append(f'vro_cases{{state="{r["state"]}"}} {r["n"]}')
        L.append("# TYPE vro_claims gauge")
        for r in st.query("SELECT status, COUNT(*) n FROM claims GROUP BY status"):
            L.append(f'vro_claims{{status="{r["status"]}"}} {r["n"]}')
        L.append("# TYPE vro_jobs gauge")
        for r in st.query("SELECT status, COUNT(*) n FROM jobs GROUP BY status"):
            L.append(f'vro_jobs{{status="{r["status"]}"}} {r["n"]}')
        r = st.one("SELECT COALESCE(SUM(cost_usd),0) c, COUNT(*) n FROM agent_runs")
        g = svc.gateway
        L += [f"vro_agent_cost_usd_total {r['c']}", f"vro_agent_runs_total {r['n']}", f"vro_llm_calls_total {g.stats['calls']}", f"vro_llm_retries_total {g.stats['retries']}",
              f"vro_llm_fallbacks_total {g.stats['fallbacks']}", f"vro_llm_tokens_in_total {g.stats['tokens_in']}", f"vro_llm_tokens_out_total {g.stats['tokens_out']}",
              f"vro_llm_latency_seconds_total {g.stats['latency_s']}"]
        for i, b in enumerate(g.breakers):
            L.append(f'vro_llm_circuit_open{{provider="{getattr(g.providers[i], "name", i)}"}} {1 if b.state == "open" else 0}')
        v = st.get("flags", "name", "audit_chain_ok")
        L.append(f"vro_audit_chain_ok {-1 if not v else int(v['value'] == '1')}")
        return PlainTextResponse("\n".join(L) + "\n")

    def cases_create(request):
        actor = actor_of(request, svc)
        key, prior = idem(request, actor)
        if prior:
            return JSONResponse(prior, status_code=200, headers={"Idempotent-Replay": "true"})
        c = wf.create_case(actor, body_json(request))
        out = {"case_id": c["case_id"], "state": c["state"]}
        remember(key, out, actor)
        return JSONResponse(out, status_code=201)

    def cases_list(request):
        actor = actor_of(request, svc)
        state = request.query_params.get("state")
        sql, p = ("SELECT c.case_id, c.state, c.proposed_tier, c.final_tier, c.requester_id, c.created_at, c.updated_at, c.emergency, v.legal_name, "
                  "(SELECT MIN(due_at) FROM gate_tasks g WHERE g.case_id=c.case_id AND g.status='OPEN') next_due, "
                  "(SELECT GROUP_CONCAT(gate) FROM gate_tasks g WHERE g.case_id=c.case_id AND g.status='OPEN') open_gates "
                  "FROM cases c LEFT JOIN vendor v ON v.vendor_id=c.vendor_id WHERE c.tenant_id=?"), [actor.tenant_id]
        if state:
            sql += " AND c.state=?"; p.append(state)
        return JSONResponse({"cases": st.query(sql + " ORDER BY c.updated_at DESC LIMIT 500", p)})

    def case_get(request):
        actor = actor_of(request, svc)
        return JSONResponse(case_view(request.path_params["cid"], actor))

    def doc_upload(request):
        actor = actor_of(request, svc)
        cid = request.path_params["cid"]
        ct = request.headers.get("content-type", "")
        if ct.startswith("application/json"):
            d = body_json(request)
            try:
                data = base64.b64decode(d["content_base64"], validate=True)
            except Exception:  # noqa: BLE001
                raise ApiError(400, "E_B64", "content_base64 must be valid base64")
            name, dtype = d.get("filename") or "upload.bin", d.get("doc_type")
        else:
            data = raw_body(request)
            name, dtype = request.headers.get("x-filename", "upload.bin"), request.headers.get("x-doc-type")
        r = wf.upload_document(actor, cid, Path(name).name, data, dtype)
        return JSONResponse(r, status_code=201 if r.get("doc_id") else 422)

    def doc_get(request):
        actor = actor_of(request, svc)
        c = wf._scoped(request.path_params["cid"], actor)
        d = st.one("SELECT * FROM documents WHERE doc_id=? AND vendor_id=? AND tenant_id=?", (request.path_params["did"], c["vendor_id"], actor.tenant_id))
        if not d:
            raise NotFound(request.path_params["did"])
        claims = []
        for e in st.query("SELECT e.page, e.quote, e.claim_id, c.statement, c.status FROM claim_evidence e JOIN claims c ON c.claim_id=e.claim_id WHERE e.doc_id=?", (d["doc_id"],)):
            claims.append(e)
        return JSONResponse({"doc": {k: d[k] for k in ("doc_id", "doc_type", "filename", "sha256", "quarantine_status", "hidden_text_flag", "injection_flags", "page_count", "uploaded_at")},
                             "pages": (d["clean_text"] or "").split("\f") if d["clean_text"] else [], "citations": claims})

    def claims_list(request):
        actor = actor_of(request, svc)
        c = wf._scoped(request.path_params["cid"], actor)
        rows = svc.ledger.get_claims(c["tenant_id"], c["vendor_id"], None, request.query_params.get("predicate"), request.query_params.get("status"),
                                     include_stale=True, with_evidence=True)
        if not request.query_params.get("status"):
            rows += [dict(r, evidence=svc.ledger.evidence(r["claim_id"]), badge=r["status"]) for r in
                     st.query("SELECT * FROM claims WHERE vendor_id=? AND status IN ('REFUTED','SUPERSEDED')", (c["vendor_id"],))]
        return JSONResponse({"claims": rows})

    def gate_decide(request):
        actor = actor_of(request, svc)
        d = GateDecision.model_validate(body_json(request))
        key, prior = idem(request, actor)
        if prior:
            return JSONResponse(prior, headers={"Idempotent-Replay": "true"})
        gate = request.path_params["gate"].upper()
        c = wf.request_emergency(actor, request.path_params["cid"], d) if gate == "GX" else wf.decide_gate(actor, request.path_params["cid"], gate, d)
        out = {"state": c["state"]}
        remember(key, out, actor)
        return JSONResponse(out)

    def screening_decide(request):
        actor = actor_of(request, svc)
        d = body_json(request)
        c = wf.decide_screening(actor, request.path_params["cid"], request.path_params["sid"], d.get("decision", ""), d.get("rationale", ""))
        return JSONResponse({"state": c["state"]})

    def finding_disposition(request):
        actor = actor_of(request, svc)
        d = body_json(request)
        return JSONResponse(wf.disposition_finding(actor, request.path_params["cid"], request.path_params["fid"], d.get("action", ""), d.get("rationale", ""), d.get("expires_at")))

    def finding_dispute(request):
        actor = actor_of(request, svc)
        d = body_json(request)
        if len((d.get("reason") or "").strip()) < 5:
            raise ApiError(422, "E_REASON", "a reason is required")
        return JSONResponse(wf.dispute_finding(actor, request.path_params["cid"], request.path_params["fid"], d["reason"]))

    def question_answer(request):
        actor = actor_of(request, svc)
        d = body_json(request)
        return JSONResponse(wf.answer_question(actor, request.path_params["cid"], request.path_params["qid"], d.get("answer", "")))

    def simple_action(request):
        actor = actor_of(request, svc)
        cid, act = request.path_params["cid"], request.path_params["action"]
        d = body_json(request) if request.method == "POST" else {}
        if act == "contracting-complete":
            c = wf.complete_contracting(actor, cid, d.get("note", "contract negotiated"))
        elif act == "proceed-with-gaps":
            c = wf.proceed_with_gaps(actor, cid)
        elif act == "hold":
            need(actor, svc, "gate:G0") if actor.role not in ("analyst", "senior_analyst") else None
            c = wf.hold(actor, cid, d.get("reason", "on hold"))
        elif act == "resume":
            c = wf.resume(actor, cid, d.get("to", "DUE_DILIGENCE"))
        elif act == "material-change":
            c = wf.material_change(actor, cid, d.get("kind", "unspecified"))
        elif act == "advance":
            wf._scoped(cid, actor)
            if request.query_params.get("async") == "1":      # slow model calls: return 202 and poll /v1/jobs/{id}
                job = jobs.submit(actor.tenant_id, cid, "advance", actor.user_id, lambda: {"state": wf.advance(cid)["state"]})
                return JSONResponse({"job_id": job["job_id"], "status": job["status"]}, status_code=202, headers={"Location": f"/v1/jobs/{job['job_id']}"})
            c = wf.advance(cid)
        else:
            raise ApiError(404, "E_NOT_FOUND", "unknown action")
        return JSONResponse({"state": c["state"]})

    def packet_get(request):
        actor = actor_of(request, svc)
        cid = request.path_params["cid"]
        wf._scoped(cid, actor)
        p = packet_mod.build(svc, cid)
        if request.query_params.get("format") == "json":
            return JSONResponse(json.loads(json.dumps(p, default=str)))
        return HTMLResponse(packet_mod.render_html(p))

    def audit_case(request):
        actor = actor_of(request, svc)
        cid = request.path_params["cid"]
        wf._scoped(cid, actor)
        return JSONResponse({"events": st.query("SELECT seq, ts, actor, actor_type, action, entity_type, entity_id, payload, hash FROM audit_events WHERE tenant_id=? AND entity_id=? ORDER BY seq", (actor.tenant_id, cid))})

    def audit_export(request):
        actor = actor_of(request, svc)
        need(actor, svc, "audit_export")
        rows = st.query("SELECT * FROM audit_events WHERE tenant_id=? ORDER BY seq", (actor.tenant_id,))
        st.audit(actor.tenant_id, actor.user_id, "human", "AUDIT_EXPORT", "tenant", actor.tenant_id, {"rows": len(rows)})
        return JSONResponse({"chain": st.verify_audit_chain(), "events": rows})

    def vendor_timeline(request):
        actor = actor_of(request, svc)
        v = st.one("SELECT * FROM vendor WHERE vendor_id=? AND tenant_id=?", (request.path_params["vid"], actor.tenant_id))
        if not v:
            raise NotFound(request.path_params["vid"])
        return JSONResponse({"vendor": v, "cases": st.query("SELECT case_id, state, final_tier, created_at FROM cases WHERE vendor_id=?", (v["vendor_id"],)),
                             "claims": svc.ledger.get_claims(actor.tenant_id, v["vendor_id"], include_stale=True),
                             "stale_debt": svc.ledger.stale_debt(actor.tenant_id)})

    def kpis(request):
        actor = actor_of(request, svc)
        t = actor.tenant_id
        q = st.query
        by_state = {r["state"]: r["n"] for r in q("SELECT state, COUNT(*) n FROM cases WHERE tenant_id=? GROUP BY state", (t,))}
        sev = {r["severity"]: r["n"] for r in q("SELECT f.severity, COUNT(*) n FROM findings f WHERE f.tenant_id=? AND f.status='OPEN' GROUP BY f.severity", (t,))}
        cl = {r["status"]: r["n"] for r in q("SELECT status, COUNT(*) n FROM claims WHERE tenant_id=? GROUP BY status", (t,))}
        total = sum(cl.values()) or 1
        cost = st.one("SELECT COALESCE(SUM(cost_usd),0) c, COUNT(*) n FROM agent_runs WHERE tenant_id=?", (t,))
        overdue = [x for x in q("SELECT due_at, gate, case_id FROM gate_tasks WHERE tenant_id=? AND status='OPEN'", (t,)) if x["due_at"] and x["due_at"] < iso(now())]
        disputes = st.one("SELECT COUNT(*) n FROM feedback WHERE tenant_id=? AND kind='finding_dispute'", (t,))["n"]
        return JSONResponse({"cases_by_state": by_state, "open_findings_by_severity": sev, "claims_by_status": cl,
                             "trusted_ratio": round(cl.get("TRUSTED", 0) / total, 3), "stale_debt": svc.ledger.stale_debt(t),
                             "sla_overdue": overdue, "finding_disputes": disputes, "agent_cost_usd": cost["c"], "agent_runs": cost["n"]})

    # ---- admin
    def admin_status(request):
        actor = actor_of(request, svc)
        need(actor, svc, "admin")
        return JSONResponse({"kill_switch": st.flag("kill_switch") == "1", "agents_killed": [r["name"] for r in st.query("SELECT name FROM flags WHERE name LIKE 'kill:%' AND value='1'")],
                             "policy_version": svc.policy.version, "policy_pack": svc.policy.pack_name, "llm_provider": svc.settings.llm_provider,
                             "activations": st.query("SELECT * FROM policy_activations WHERE tenant_id=? ORDER BY created_at DESC LIMIT 20", (actor.tenant_id,)),
                             "audit_chain": st.verify_audit_chain()})

    def admin_kill(request):
        actor = actor_of(request, svc)
        need(actor, svc, "kill_switch")
        d = body_json(request)
        name = f"kill:{d['agent']}" if d.get("agent") else "kill_switch"
        st.set_flag(name, "1" if d.get("on") else "0", actor.user_id)
        st.audit(actor.tenant_id, actor.user_id, "human", "KILL_SWITCH", "flag", name, {"on": bool(d.get("on"))})
        return JSONResponse({"flag": name, "on": bool(d.get("on"))})

    def policy_request(request):
        actor = actor_of(request, svc)
        need(actor, svc, "policy_activate")
        d = body_json(request)
        pack = d.get("pack", "")
        if not (Path(svc.settings.policy_dir) / "packs" / pack / "scoring.yaml").exists():
            raise ApiError(404, "E_PACK", "unknown policy pack")
        aid = new_id("pa_")
        st.insert("policy_activations", {"activation_id": aid, "tenant_id": actor.tenant_id, "pack": pack, "status": "REQUESTED", "requested_by": actor.user_id,
                                         "eval_passed": 0, "created_at": iso(now())})
        st.audit(actor.tenant_id, actor.user_id, "human", "POLICY_ACTIVATION_REQUESTED", "policy", aid, {"pack": pack})
        return JSONResponse({"activation_id": aid, "status": "REQUESTED"}, status_code=201)

    def policy_eval(request):
        actor = actor_of(request, svc)
        need(actor, svc, "policy_activate")
        a = st.get("policy_activations", "activation_id", request.path_params["aid"])
        if not a or a["tenant_id"] != actor.tenant_id:
            raise NotFound(request.path_params["aid"])
        from evals.runner import run_all   # imported lazily: evals are a dev/CI component
        rep = run_all(pack=a["pack"], quick=True)
        st.update("policy_activations", "activation_id", a["activation_id"], {"eval_passed": int(rep["passed"])})
        st.audit(actor.tenant_id, actor.user_id, "human", "POLICY_EVAL_RUN", "policy", a["activation_id"], {"passed": rep["passed"]})
        return JSONResponse({"passed": rep["passed"], "failures": rep.get("failures", [])})

    def policy_approve(request):
        actor = actor_of(request, svc)
        need(actor, svc, "policy_activate")
        a = st.get("policy_activations", "activation_id", request.path_params["aid"])
        if not a or a["tenant_id"] != actor.tenant_id:
            raise NotFound(request.path_params["aid"])
        if a["requested_by"] == actor.user_id:
            raise PolicyError("E_4EYES", "policy activation needs a second administrator")
        if not a["eval_passed"]:
            raise PolicyError("E_EVAL_GATE", "policy pack has not passed the evaluation gate (R9)")
        svc.reload_policy(a["pack"])
        st.update("policy_activations", "activation_id", a["activation_id"], {"status": "ACTIVE", "approved_by": actor.user_id, "decided_at": iso(now())})
        st.audit(actor.tenant_id, actor.user_id, "human", "POLICY_ACTIVATED", "policy", a["activation_id"], {"pack": a["pack"], "version": svc.policy.version})
        return JSONResponse({"status": "ACTIVE", "policy_version": svc.policy.version})

    def sweep(request):
        actor = actor_of(request, svc)
        need(actor, svc, "admin")
        out = wf.sweep(actor.tenant_id)
        out["orphaned_jobs"] = jobs.reap(actor.tenant_id)
        out["audit_chain_ok"] = _verify_audit(actor.user_id)["ok"]
        return JSONResponse(out)

    def _verify_audit(by: str) -> dict:
        r = st.verify_audit_chain()
        st.set_flag("audit_chain_ok", "1" if r["ok"] else "0", by)
        if not r["ok"]:
            log("AUDIT_CHAIN_BROKEN", logging.CRITICAL, first_bad_seq=r["first_bad_seq"])
        return r

    def audit_verify(request):
        actor = actor_of(request, svc)
        need(actor, svc, "admin")
        return JSONResponse(_verify_audit(actor.user_id))

    def job_get(request):
        actor = actor_of(request, svc)
        j = st.one("SELECT * FROM jobs WHERE job_id=? AND tenant_id=?", (request.path_params["jid"], actor.tenant_id))
        if not j:
            raise NotFound(request.path_params["jid"])
        return JSONResponse(j)

    # ---- dev/demo helpers (only when dev auth is on): load a SYNTHETIC scenario as a new case
    def dev_scenarios(request):
        actor = actor_of(request, svc)
        if not svc.settings.dev_auth:
            raise ApiError(404, "E_NOT_FOUND", "not found")
        base = ROOT / "data" / "synth" / "vendors"
        out = []
        for d in sorted(base.glob("*/intake.json")) if base.exists() else []:
            exp = json.loads((d.parent / "expected.json").read_text())
            out.append({"key": d.parent.name, "name": json.loads(d.read_text())["legal_name"], "note": exp.get("note", ""), "docs": len(list((d.parent / "docs").glob("*")))})
        return JSONResponse({"scenarios": out})

    def dev_load(request):
        actor = actor_of(request, svc)
        if not svc.settings.dev_auth:
            raise ApiError(404, "E_NOT_FOUND", "not found")
        key = request.path_params["key"]
        d = ROOT / "data" / "synth" / "vendors" / Path(key).name
        if not (d / "intake.json").exists():
            raise ApiError(404, "E_NOT_FOUND", "unknown scenario")
        c = wf.create_case(actor, json.loads((d / "intake.json").read_text()))
        loader = Actor("demo-loader", "analyst", actor.tenant_id)
        for f in sorted((d / "docs").glob("*")):
            wf.upload_document(loader, c["case_id"], f.name, f.read_bytes())
        return JSONResponse({"case_id": c["case_id"], "state": wf.case(c["case_id"])["state"]}, status_code=201)

    # ---- webhooks (HMAC + timestamp + nonce, plan §8.5)
    def webhook(request):
        source = request.path_params["source"]
        secret = svc.settings.webhook_secrets.get(source)
        if not secret:
            raise ApiError(404, "E_SOURCE", "unknown webhook source")
        raw = raw_body(request)
        ts, nonce, sig = request.headers.get("x-timestamp", ""), request.headers.get("x-nonce", ""), request.headers.get("x-signature", "")
        try:
            skew = abs(time.time() - float(ts)) if not _frozen() else 0
        except ValueError:
            raise ApiError(401, "E_SIG", "bad timestamp")
        if skew > 300:
            raise ApiError(401, "E_SIG", "timestamp outside the allowed window")
        want = hmac.new(secret.encode(), ts.encode() + b"." + nonce.encode() + b"." + raw, hashlib.sha256).hexdigest()
        if not (sig and hmac.compare_digest(sig, want)):
            METRICS[("webhook", "bad_sig")] += 1
            raise ApiError(401, "E_SIG", "invalid signature")
        if st.one("SELECT 1 x FROM nonces WHERE source=? AND nonce=?", (source, nonce)):
            raise ApiError(409, "E_REPLAY", "nonce already used")
        st.insert("nonces", {"source": source, "nonce": nonce, "ts": ts})
        d = json.loads(raw or b"{}")
        tenant = d.get("tenant_id", "t_demo")
        if source == "sanctions-list-updated":
            svc.sanctions = SanctionsList(d.get("list_name", "SYNTHETIC_SDN"), d["entities"], d.get("source", "SYNTHETIC"))
            ch = svc.ledger.run_staleness(tenant, sources={("list", svc.sanctions.name): svc.sanctions.version})
            flagged = wf.rescreen_active(tenant)
            st.audit(tenant, f"webhook:{source}", "system", "SANCTIONS_LIST_UPDATED", "list", svc.sanctions.name,
                     {"version": svc.sanctions.version, "stale": len(ch), "cases_needing_review": flagged})
            return JSONResponse({"list_version": svc.sanctions.version, "cases_needing_review": flagged})
        if source == "vendor-portal":
            data = base64.b64decode(d["content_base64"])
            r = wf.upload_document(Actor("vendor-portal", "analyst", tenant), d["case_id"], Path(d["filename"]).name, data)
            return JSONResponse(r)
        raise ApiError(404, "E_SOURCE", "unhandled source")

    routes = [
        Route("/healthz", healthz), Route("/readyz", offload(readyz)), Route("/metrics", offload(metrics)),
        Route("/v1/cases", offload(cases_create), methods=["POST"]), Route("/v1/cases", offload(cases_list), methods=["GET"]),
        Route("/v1/cases/{cid}", offload(case_get)), Route("/v1/cases/{cid}/documents", offload(doc_upload), methods=["POST"]),
        Route("/v1/cases/{cid}/documents/{did}", offload(doc_get)), Route("/v1/cases/{cid}/claims", offload(claims_list)),
        Route("/v1/cases/{cid}/gates/{gate}", offload(gate_decide), methods=["POST"]),
        Route("/v1/cases/{cid}/screening/{sid}", offload(screening_decide), methods=["POST"]),
        Route("/v1/cases/{cid}/findings/{fid}/disposition", offload(finding_disposition), methods=["POST"]),
        Route("/v1/cases/{cid}/findings/{fid}/dispute", offload(finding_dispute), methods=["POST"]),
        Route("/v1/cases/{cid}/questions/{qid}/answer", offload(question_answer), methods=["POST"]),
        Route("/v1/cases/{cid}/actions/{action}", offload(simple_action), methods=["POST"]),
        Route("/v1/cases/{cid}/packet", offload(packet_get)), Route("/v1/cases/{cid}/audit", offload(audit_case)),
        Route("/v1/audit/export", offload(audit_export)), Route("/v1/vendors/{vid}/timeline", offload(vendor_timeline)), Route("/v1/kpis", offload(kpis)),
        Route("/v1/admin/status", offload(admin_status)), Route("/v1/admin/kill-switch", offload(admin_kill), methods=["POST"]),
        Route("/v1/admin/policy/requests", offload(policy_request), methods=["POST"]),
        Route("/v1/admin/policy/requests/{aid}/eval", offload(policy_eval), methods=["POST"]),
        Route("/v1/admin/policy/requests/{aid}/approve", offload(policy_approve), methods=["POST"]),
        Route("/v1/admin/sweep", offload(sweep), methods=["POST"]), Route("/v1/admin/audit/verify", offload(audit_verify), methods=["POST"]),
        Route("/v1/jobs/{jid}", offload(job_get)), Route("/v1/dev/scenarios", offload(dev_scenarios)), Route("/v1/dev/scenarios/{key}/load", offload(dev_load), methods=["POST"]), Route("/v1/webhooks/{source}", offload(webhook), methods=["POST"]),
    ]
    ui_dir = ROOT / "ui"
    if ui_dir.exists():
        routes.append(Mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui"))

    allowed_hosts = {h.strip().lower() for h in svc.settings.allowed_hosts.split(",") if h.strip()}
    prod = svc.settings.app_env in ("prod", "production", "staging")

    class Middleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            trace = request.headers.get("x-trace-id", "")[:64] if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", request.headers.get("x-trace-id", "")) else new_id("tr_")
            request.state.trace = trace
            t0 = time.perf_counter()
            try:
                host = request.headers.get("host", "").split(":")[0].lower()
                if allowed_hosts and host not in allowed_hosts:
                    resp = jerr(400, "E_HOST", "host not allowed", trace)
                elif int(request.headers.get("content-length") or 0) > MAX_BODY:           # reject before buffering a huge body
                    resp = jerr(413, "E_SIZE", "request body too large", trace)
                else:
                    with span("http.request", method=request.method):
                        resp = await call_next(request)
            except Exception as e:  # noqa: BLE001
                if not isinstance(e, (ApiError, NotFound, PolicyError, ValidationError)):
                    log("unhandled_error", logging.ERROR, trace_id=trace, path=request.url.path, error=type(e).__name__)
                resp = handle(e, trace)
            dt = time.perf_counter() - t0
            resp.headers["X-Trace-Id"] = trace
            resp.headers["X-Content-Type-Options"] = "nosniff"
            resp.headers["Referrer-Policy"] = "no-referrer"
            resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            resp.headers["Cache-Control"] = "no-store"
            resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            if prod:
                resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
            METRICS[(request.method, resp.status_code)] += 1
            if request.url.path.startswith("/v1"):
                LATENCY.observe((request.method, _ID_SEG.sub("/:id", request.url.path)), dt)
                a = getattr(request.state, "actor", None)
                if svc.settings.app_env != "test":
                    log("http", trace_id=trace, method=request.method, path=request.url.path, status=resp.status_code, ms=int(dt * 1000),
                        user=a.user_id if a else None, tenant=a.tenant_id if a else None)
            return resp

    def handle(e: Exception, trace: str) -> Response:
        if isinstance(e, ApiError):
            return jerr(e.status, e.code, e.message, trace, e.headers)
        if isinstance(e, PolicyError):
            return jerr(403 if e.code == "E_ROLE" else 409, e.code, e.message, trace)
        if isinstance(e, NotFound):
            return jerr(404, "E_NOT_FOUND", "not found", trace)
        if isinstance(e, ValidationError):
            return JSONResponse({"error": {"code": "E_VALIDATION", "message": "invalid request", "trace_id": trace,
                                           "details": [{"loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors()]}}, status_code=422)
        if isinstance(e, KillSwitchActive):
            return jerr(503, "E_KILL_SWITCH", str(e), trace)
        if isinstance(e, BudgetExceeded):
            return jerr(402, "E_BUDGET", str(e), trace)
        if isinstance(e, GatewayError):
            return jerr(502, "E_LLM", "model gateway error", trace)
        return jerr(500, "E_INTERNAL", "internal error", trace)      # details stay in server logs, never in the response

    app = Starlette(routes=routes)
    app.add_middleware(Middleware)
    app.state.svc = svc
    app.state.ctx = C
    return app


def _frozen() -> bool:
    from . import util
    return util._NOW_OVERRIDE is not None


def create_app() -> Starlette:
    settings = Settings()
    setup_logging(settings.log_level)
    problems = production_problems(settings)
    if problems:                                   # refuse to start insecurely rather than warn and serve
        raise RuntimeError("refusing to start; fix configuration:\n  - " + "\n  - ".join(problems))
    init_tracing(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", ""))
    anyio.to_thread.current_default_thread_limiter().total_tokens = settings.api_threads
    return build_app(Services(settings))
