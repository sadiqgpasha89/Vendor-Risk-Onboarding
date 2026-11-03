"""A0 Orchestrator / case workflow engine. A deterministic state machine (plan §3, §14: T-020/T-021) - the stand-in for Temporal here.

* advance() drives automated steps until a human gate or missing input stops it; every step is idempotent (R6).
* Gates are decided by humans only; role, segregation of duties and hard rules are enforced by PolicyEngine (R1, R3).
* Agents never call this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from . import docproc
from .agents import assess as assess_mod
from .agents import comms, intake as intake_agent, reader, screening_agent, steward, tiering, verifier
from .agents.services import Services
from .models import GateDecision, Question, VendorIntake
from .policy import EMERGENCY_FROM, PolicyError
from .util import iso, new_id, now, parse_date


@dataclass
class Actor:
    user_id: str
    role: str
    tenant_id: str = "t_demo"


class NotFound(Exception):
    pass


def case_locked(fn):
    """Serialise mutations of one case (this process via an RLock, other replicas via a Postgres advisory lock). Two humans clicking at once,
    a webhook racing an analyst, or a retried request can no longer interleave state transitions."""
    import functools
    import inspect
    sig = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(self, *a, **k):
        cid = sig.bind(self, *a, **k).arguments.get("case_id")
        if not cid:
            return fn(self, *a, **k)
        with self.store.advisory_lock(f"case:{cid}"):
            return fn(self, *a, **k)
    return wrapper


class Workflow:
    def __init__(self, svc: Services):
        self.svc = svc
        self.store = svc.store
        self.policy = svc.policy

    # ------------------------------------------------------------------ helpers
    def case(self, case_id: str) -> dict:
        try:
            return self.svc.case(case_id)
        except KeyError:
            raise NotFound(case_id)

    def _scoped(self, case_id: str, actor: Actor) -> dict:
        c = self.case(case_id)
        if c["tenant_id"] != actor.tenant_id:        # tenant isolation: a foreign case looks like it does not exist (GR-009)
            raise NotFound(case_id)
        return c

    def _ctx(self, case: dict, **upd) -> dict:
        ctx = dict(case.get("context") or {})
        ctx.update(upd)
        self.store.update("cases", "case_id", case["case_id"], {"context": ctx, "updated_at": iso(now())})
        return ctx

    def _to(self, case: dict, new: str, actor: str, reason: str = "") -> dict:
        self.policy.check_transition(case["state"], new)
        self.store.update("cases", "case_id", case["case_id"], {"state": new, "updated_at": iso(now())})
        self.store.audit(case["tenant_id"], actor, "system" if actor.startswith("system") else "human", "STATE_CHANGE", "case", case["case_id"],
                         {"from": case["state"], "to": new, "reason": reason})
        if new in ("REJECTED",):
            self.store.update("vendor", "vendor_id", case["vendor_id"], {"status": "REJECTED", "updated_at": iso(now())})
        return self.case(case["case_id"])

    def _open_task(self, case: dict, gate: str, payload: dict | None = None) -> str:
        ex = self.store.one("SELECT task_id FROM gate_tasks WHERE case_id=? AND gate=? AND status='OPEN'", (case["case_id"], gate))
        if ex:
            return ex["task_id"]
        tier = case["final_tier"] or case["proposed_tier"]
        tid = new_id("gt_")
        self.store.insert("gate_tasks", {"task_id": tid, "tenant_id": case["tenant_id"], "case_id": case["case_id"], "gate": gate, "status": "OPEN",
                                         "role_required": self.policy.gate_roles(gate, tier), "created_at": iso(now()),
                                         "due_at": iso(now() + timedelta(hours=self.policy.sla_hours(gate, tier))), "payload": payload or {}})
        self.store.audit(case["tenant_id"], "system:workflow", "system", "GATE_OPENED", "case", case["case_id"], {"gate": gate, "task_id": tid})
        return tid

    def _close_task(self, case_id: str, gate: str, by: str) -> None:
        self.store.execute("UPDATE gate_tasks SET status='DONE' WHERE case_id=? AND gate=? AND status='OPEN'", (case_id, gate))

    def _task(self, case_id: str, gate: str, status: str = "OPEN"):
        return self.store.one("SELECT * FROM gate_tasks WHERE case_id=? AND gate=? AND status=?", (case_id, gate, status))

    def _question(self, case: dict, role: str, text: str, why: str, blocking: bool = False) -> None:
        dup = self.store.one("SELECT 1 x FROM questions WHERE case_id=? AND text=? AND status='OPEN'", (case["case_id"], text))
        if not dup:
            self.store.insert("questions", {"question_id": new_id("q_"), "tenant_id": case["tenant_id"], "case_id": case["case_id"], "to_role": role,
                                            "text": text, "why": why, "blocking": blocking, "options": None, "status": "OPEN", "created_at": iso(now())})

    def open_criticals(self, case_id: str) -> int:
        rows = self.store.query("SELECT * FROM findings WHERE case_id=? AND status='OPEN' AND severity='CRITICAL'", (case_id,))
        n = 0
        for f in rows:
            if f["disposition"] == "REMEDIATED":
                continue
            if f["disposition"] == "ACCEPT_RISK" and f["exception_expires"] and (parse_date(f["exception_expires"]) or now().date()) >= now().date():
                continue
            n += 1
        return n

    # ------------------------------------------------------------------ creation
    def create_case(self, actor: Actor, intake: dict) -> dict:
        if not self.policy.role_can(actor.role, "create_case"):
            raise PolicyError("E_ROLE", f"role '{actor.role}' cannot create cases")
        vi = VendorIntake.model_validate(intake)
        self.store.ensure_tenant(actor.tenant_id, actor.tenant_id)
        vid, cid, ts = new_id("v_"), new_id("case_"), iso(now())
        self.store.insert("vendor", {"vendor_id": vid, "tenant_id": actor.tenant_id, "legal_name": vi.legal_name, "trade_names": vi.trade_names,
                                     "country_iso2": vi.country_iso2, "reg_number": vi.registration_number, "lei": vi.lei, "website": vi.website,
                                     "status": "PROSPECT", "tier": None, "created_at": ts, "updated_at": ts})
        self.store.insert("cases", {"case_id": cid, "tenant_id": actor.tenant_id, "vendor_id": vid, "requester_id": actor.user_id, "state": "NEW",
                                    "intake": vi.model_dump(), "jurisdictions": vi.jurisdictions, "emergency": vi.emergency, "context": {},
                                    "created_at": ts, "updated_at": ts})
        self.store.audit(actor.tenant_id, actor.user_id, "human", "CASE_CREATED", "case", cid, {"vendor": vi.legal_name})
        return self.advance(cid)

    # ------------------------------------------------------------------ documents
    @case_locked
    def upload_document(self, actor: Actor, case_id: str, filename: str, data: bytes, doc_type: str | None = None) -> dict:
        case = self._scoped(case_id, actor)
        if not (self.policy.role_can(actor.role, "upload")):
            raise PolicyError("E_ROLE", f"role '{actor.role}' cannot upload documents")
        if case["state"] in ("REJECTED", "CLOSED"):
            raise PolicyError("E_STATE", "case is closed")
        pd = docproc.process(data, filename, self.svc.settings.max_upload_bytes, self.svc.settings.max_pages, self.svc.settings.pdf_cfg())
        dtype = doc_type or pd.doc_type
        dup = self.store.one("SELECT * FROM documents WHERE vendor_id=? AND sha256=?", (case["vendor_id"], pd.sha256))
        if dup:
            return {"doc_id": dup["doc_id"], "duplicate": True, "doc_type": dup["doc_type"], "status": dup["quarantine_status"]}
        if pd.status == "REJECTED":
            self.store.audit(case["tenant_id"], actor.user_id, "human", "DOCUMENT_REJECTED", "case", case_id, {"filename": filename, "reason": pd.reason})
            return {"doc_id": None, "status": "REJECTED", "reason": pd.reason}
        prev = None
        if pd.status == "ACCEPTED":
            prev = self.store.one("SELECT doc_id FROM documents WHERE vendor_id=? AND doc_type=? AND quarantine_status='ACCEPTED' AND doc_id NOT IN "
                                  "(SELECT supersedes_doc_id FROM documents WHERE supersedes_doc_id IS NOT NULL) ORDER BY uploaded_at DESC LIMIT 1",
                                  (case["vendor_id"], dtype))
        did = new_id("doc_")
        self.store.insert("documents", {
            "doc_id": did, "tenant_id": case["tenant_id"], "case_id": case_id, "vendor_id": case["vendor_id"], "doc_type": dtype, "filename": filename,
            "mime": pd.mime, "sha256": pd.sha256, "size": len(data), "quarantine_status": pd.status, "hidden_text_flag": pd.hidden_text_flag,
            "injection_flags": pd.injection_flags, "page_count": len(pd.clean_pages), "period_start": iso(pd.period_start), "period_end": iso(pd.period_end),
            "valid_until": iso(pd.valid_until), "supersedes_doc_id": prev["doc_id"] if prev else None, "uploaded_by": actor.user_id,
            "uploaded_at": iso(now()), "raw_text": pd.raw_text if pd.status == "ACCEPTED" else None,
            "clean_text": pd.clean_text if pd.status == "ACCEPTED" else None, "language": pd.language, "version": 1, "processed": 0,
            "ocr_quality": pd.ocr_quality, "parse_meta": pd.parse_meta})
        self.store.audit(case["tenant_id"], actor.user_id, "human", "DOCUMENT_UPLOADED", "document", did,
                         {"filename": filename, "doc_type": dtype, "sha256": pd.sha256, "flags": [f["kind"] for f in pd.injection_flags]})
        if pd.status != "ACCEPTED":
            self._question(case, "analyst", f"'{filename}' could not be parsed ({pd.reason}). Please provide a DOCX, HTML, text or text-based PDF version.",
                           "The document cannot be analysed until it is readable.", False)
            return {"doc_id": did, "status": pd.status, "reason": pd.reason, "doc_type": dtype}
        # new evidence for a type supersedes the earlier gap claim and old unverified claims
        for g in self.store.query("SELECT claim_id FROM claims WHERE vendor_id=? AND predicate=? AND status IN ('TRUSTED','UNTRUSTED')",
                                  (case["vendor_id"], f"document_missing:{dtype}")):
            self.svc.ledger.set_status(g["claim_id"], "SUPERSEDED", "system:workflow", "document now provided")
        if prev:
            for c in self.store.query("SELECT DISTINCT c.claim_id FROM claims c JOIN claim_evidence e ON e.claim_id=c.claim_id WHERE e.doc_id=? AND c.status='UNTRUSTED'",
                                      (prev["doc_id"],)):
                self.svc.ledger.set_status(c["claim_id"], "SUPERSEDED", "system:workflow", "source document superseded")
            steward.sweep(self.svc, case["tenant_id"], case["vendor_id"])
        # a change after analysis started sends the case back for re-assessment (material-change loop)
        case = self.case(case_id)
        if case["state"] in ("VERIFICATION", "HUMAN_REVIEW") or (case["state"] in ("MONITORING",) and prev):
            self._close_task(case_id, "G3", "system")
            self._to(case, "ASSESSMENT", "system:workflow", "new or updated evidence received")
        self.advance(case_id)
        return {"doc_id": did, "status": "ACCEPTED", "doc_type": dtype, "supersedes": prev["doc_id"] if prev else None,
                "flags": [f["kind"] for f in pd.injection_flags]}

    # ------------------------------------------------------------------ engine
    @case_locked
    def advance(self, case_id: str) -> dict:
        for _ in range(25):
            case = self.case(case_id)
            fn = getattr(self, "_st_" + case["state"].lower(), None)
            if not fn or not fn(case):
                break
        return self.case(case_id)

    def _st_new(self, case):
        res = intake_agent.run(self.svc, case)["resolution"]
        self._ctx(case, resolution=res)
        top = (res.get("candidates") or [None])[0] if isinstance(res, dict) else None
        if res.get("decision") == "AUTO_LINK" and top:
            self._link(case, top["vendor_id"], "system:A1")
        elif res.get("decision") == "HUMAN_CONFIRM":
            self._open_task(case, "G0", {"candidates": res.get("candidates", [])[:3]})
        self._to(case, "INTAKE_REVIEW", "system:workflow")
        return True

    def _link(self, case: dict, vendor_id: str, by: str) -> None:
        old = case["vendor_id"]
        if vendor_id == old:
            return
        self.store.update("cases", "case_id", case["case_id"], {"vendor_id": vendor_id})
        self.store.execute("DELETE FROM vendor WHERE vendor_id=? AND tenant_id=?", (old, case["tenant_id"]))
        self.store.audit(case["tenant_id"], by, "system", "ENTITY_LINKED", "case", case["case_id"], {"from": old, "to": vendor_id})

    def _st_intake_review(self, case):
        if self._task(case["case_id"], "G0"):
            return False
        self._to(case, "SCREENING", "system:workflow")
        return True

    def _st_screening(self, case):
        screening_agent.run(self.svc, case)
        n = screening_agent.unresolved(self.svc, case["case_id"])
        if n > 0:
            self._open_task(case, "G1", {"potential_matches": n})
            self._to(case, "HUMAN_SCREEN_REVIEW", "system:workflow", f"{n} potential match(es)")
        else:
            self.policy.check_screening_to_tiering(0)
            self._to(case, "TIERING", "system:workflow", "no potential matches")
        return True

    def _st_human_screen_review(self, case):
        n = screening_agent.unresolved(self.svc, case["case_id"])
        if n > 0:
            return False
        if self.store.one("SELECT 1 x FROM screening_results WHERE case_id=? AND human_disposition='CONFIRM_MATCH'", (case["case_id"],)):
            self._close_task(case["case_id"], "G1", "system")
            self._to(case, "REJECTED", "system:workflow", "sanctions match confirmed by AML")
            return False
        self.policy.check_screening_to_tiering(n)
        self._close_task(case["case_id"], "G1", "system")
        self._to(case, "TIERING", "system:workflow", "all matches dispositioned")
        return True

    def _st_tiering(self, case):
        tp = tiering.run(self.svc, case)
        case = self.case(case["case_id"])
        if case["final_tier"] is None:
            if tp["tier"] in self.policy.gates["requires_g2_tiers"]:
                self._open_task(case, "G2", {"proposal": tp})
                return False
            self.store.update("cases", "case_id", case["case_id"], {"final_tier": tp["tier"]})
        case = self.case(case["case_id"])
        self.store.update("vendor", "vendor_id", case["vendor_id"], {"tier": case["final_tier"], "updated_at": iso(now())})
        self._to(case, "DUE_DILIGENCE", "system:workflow", f"tier T{case['final_tier']}")
        return True

    def missing_docs(self, case: dict) -> list[str]:
        plan = self.svc.case_plan(case["case_id"])
        have = {d["doc_type"] for d in self.svc.current_docs(case["tenant_id"], case["vendor_id"])}
        return [d for d in plan["required_docs"] if d not in have]

    def _st_due_diligence(self, case):
        missing = self.missing_docs(case)
        ctx = case.get("context") or {}
        if missing and not ctx.get("proceed_with_gaps"):
            if sorted(ctx.get("drafted_for", [])) != sorted(missing):
                comms.draft_document_request(self.svc, case, missing)
                self._ctx(case, drafted_for=missing)
            return False
        self._to(case, "ASSESSMENT", "system:workflow", "evidence complete" if not missing else "proceeding with documented gaps")
        return True

    def _st_assessment(self, case):
        reader.run(self.svc, case)
        steward.sweep(self.svc, case["tenant_id"], case["vendor_id"])
        for c in self.svc.ledger.get_claims(case["tenant_id"], case["vendor_id"], status="STALE"):     # correction in the flow of work
            self.svc.ledger.verify_claim(case["tenant_id"], c["claim_id"])
        self._to(case, "VERIFICATION", "system:workflow")
        return True

    def _st_verification(self, case):
        v = verifier.run(self.svc, case)
        a = assess_mod.assess(self.svc, case, "final")
        if v.get("refuted"):
            self._question(case, "analyst", f"{v['refuted']} extracted claim(s) failed independent verification and were excluded from scoring.",
                           "Excluded claims count as missing evidence (zero coverage).", False)
        if a["missing_docs"]:
            comms.draft_document_request(self.svc, case, a["missing_docs"])
        crit = [dict(f) for f in self.store.query("SELECT * FROM findings WHERE case_id=? AND status='OPEN' AND severity IN ('CRITICAL','HIGH')", (case["case_id"],))]
        if crit:
            comms.draft_remediation(self.svc, case, crit)
        self._open_task(case, "G3", {"assessment_id": a["assessment_id"]})
        self._to(case, "HUMAN_REVIEW", "system:workflow", f"residual {a['residual']['band']}")
        return True

    def _st_onboarded(self, case):
        self.store.update("vendor", "vendor_id", case["vendor_id"], {"status": "ONBOARDED", "tier": case["final_tier"], "updated_at": iso(now())})
        self._to(case, "MONITORING", "system:workflow")
        return False

    # ------------------------------------------------------------------ gates (humans only)
    def _decide(self, case: dict, gate: str, actor: Actor, d: GateDecision) -> None:
        tier = case["final_tier"] or case["proposed_tier"]
        if not self.policy.role_can(actor.role, f"gate:{self.policy.gate_name(gate, tier)}") and gate not in ("G1",):
            pass  # gate_roles is authoritative
        self.policy.check_gate_actor(gate, tier, actor.role)
        self.store.insert("approvals", {"approval_id": new_id("ap_"), "tenant_id": case["tenant_id"], "case_id": case["case_id"], "gate": gate,
                                        "approver_id": actor.user_id, "decision": d.decision, "conditions": d.conditions, "rationale": d.rationale,
                                        "decided_at": iso(now())})
        self.store.audit(case["tenant_id"], actor.user_id, "human", f"GATE_{gate}_{d.decision}", "case", case["case_id"],
                         {"role": actor.role, "rationale": d.rationale, "conditions": d.conditions})

    @case_locked
    def decide_gate(self, actor: Actor, case_id: str, gate: str, d: GateDecision) -> dict:
        case = self._scoped(case_id, actor)
        gate = gate.upper()
        if gate == "G4":
            gate = "G4"
        handler = {"G0": self._g0, "G2": self._g2, "G3": self._g3, "G4": self._g4}.get(gate)
        if not handler:
            raise PolicyError("E_GATE", f"gate {gate} cannot be decided here (G1 uses decide_screening, GX uses request_emergency)")
        handler(case, actor, d)
        return self.advance(case_id)

    def _g0(self, case, actor, d):
        if case["state"] != "INTAKE_REVIEW" or not self._task(case["case_id"], "G0"):
            raise PolicyError("E_STATE", "no open G0 task")
        self._decide(case, "G0", actor, d)
        if d.decision == "CONFIRM" and d.subject:
            self._link(case, d.subject, actor.user_id)
        elif d.decision not in ("REJECT", "CONFIRM"):
            raise PolicyError("E_DECISION", "G0 accepts CONFIRM (subject=existing vendor id) or REJECT (treat as a new vendor)")
        self._close_task(case["case_id"], "G0", actor.user_id)

    def _g2(self, case, actor, d):
        if case["state"] != "TIERING" or not self._task(case["case_id"], "G2"):
            raise PolicyError("E_STATE", "no open G2 task")
        self._decide(case, "G2", actor, d)
        if d.decision == "CONFIRM":
            tier = case["proposed_tier"]
        elif d.decision == "OVERRIDE" and d.override_tier:
            tier = d.override_tier
            if len(d.rationale.strip()) < 15:
                raise PolicyError("E_RATIONALE", "a tier override needs a substantive rationale")
        else:
            raise PolicyError("E_DECISION", "G2 accepts CONFIRM or OVERRIDE(with override_tier)")
        self.store.update("cases", "case_id", case["case_id"], {"final_tier": tier})
        self._close_task(case["case_id"], "G2", actor.user_id)

    def _g3(self, case, actor, d):
        if case["state"] != "HUMAN_REVIEW":
            raise PolicyError("E_STATE", "case is not in HUMAN_REVIEW")
        self._decide(case, "G3", actor, d)
        if d.decision == "APPROVE":
            self.policy.check_can_approve(self.open_criticals(case["case_id"]))
            self.store.update("cases", "case_id", case["case_id"], {"preparer_id": actor.user_id})
            self._close_task(case["case_id"], "G3", actor.user_id)
            self._to(self.case(case["case_id"]), "CONTRACTING", actor.user_id, "findings reviewed")
        elif d.decision == "REJECT":
            self._close_task(case["case_id"], "G3", actor.user_id)
            self._to(case, "REJECTED", actor.user_id, d.rationale)
        elif d.decision == "REQUEST_REWORK":
            self._close_task(case["case_id"], "G3", actor.user_id)
            self._to(case, "ASSESSMENT", actor.user_id, "reviewer requested rework")
        else:
            raise PolicyError("E_DECISION", "G3 accepts APPROVE, REJECT or REQUEST_REWORK")

    @case_locked
    def complete_contracting(self, actor: Actor, case_id: str, note: str = "contract negotiated") -> dict:
        case = self._scoped(case_id, actor)
        if actor.role not in ("analyst", "senior_analyst", "legal"):
            raise PolicyError("E_ROLE", "only analyst/senior_analyst/legal may complete contracting")
        if case["state"] != "CONTRACTING":
            raise PolicyError("E_STATE", "case is not in CONTRACTING")
        self.store.audit(case["tenant_id"], actor.user_id, "human", "CONTRACTING_COMPLETE", "case", case_id, {"note": note})
        self._to(case, "FINAL_APPROVAL", actor.user_id, note)
        self._open_task(self.case(case_id), "G4", {})
        return self.advance(case_id)

    def _g4(self, case, actor, d):
        if case["state"] != "FINAL_APPROVAL":
            raise PolicyError("E_STATE", "case is not in FINAL_APPROVAL")
        if d.decision == "REJECT":
            self._decide(case, "G4", actor, d)
            self._close_task(case["case_id"], "G4", actor.user_id)
            self._to(case, "REJECTED", actor.user_id, d.rationale)
            return
        if d.decision != "APPROVE":
            raise PolicyError("E_DECISION", "G4 accepts APPROVE or REJECT")
        self.policy.check_gate_actor("G4", case["final_tier"], actor.role)
        self.policy.check_sod(actor.user_id, case["requester_id"], case["preparer_id"])
        self.policy.check_can_approve(self.open_criticals(case["case_id"]))
        if d.conditions or d.expires_at:
            exp = parse_date(d.expires_at) if d.expires_at else None
            if not exp:
                raise PolicyError("E_CONDITIONAL_EXPIRY", "a conditional approval needs expires_at")
            self.policy.check_conditional_expiry((exp - now().date()).days)
            self.store.update("cases", "case_id", case["case_id"], {"conditional_expires": iso(exp)})
        self._decide(case, "G4", actor, d)
        self._close_task(case["case_id"], "G4", actor.user_id)
        self._to(case, "ONBOARDED", actor.user_id, "final approval")

    # G1: per-subject screening disposition by AML. Agents only recommended (R3).
    @case_locked
    def decide_screening(self, actor: Actor, case_id: str, screening_id: str, decision: str, rationale: str) -> dict:
        case = self._scoped(case_id, actor)
        self.policy.check_gate_actor("G1", case["final_tier"], actor.role)
        if decision not in ("CLEAR", "CONFIRM_MATCH"):
            raise PolicyError("E_DECISION", "G1 accepts CLEAR or CONFIRM_MATCH")
        if len(rationale.strip()) < 10:
            raise PolicyError("E_RATIONALE", "a screening disposition needs a written rationale")
        row = self.store.one("SELECT * FROM screening_results WHERE screening_id=? AND case_id=?", (screening_id, case_id))
        if not row:
            raise NotFound(screening_id)
        if row["human_disposition"]:
            raise PolicyError("E_STATE", "already dispositioned")
        self.store.update("screening_results", "screening_id", screening_id, {"human_disposition": decision, "dispositioned_by": actor.user_id, "rationale": rationale})
        self.store.insert("approvals", {"approval_id": new_id("ap_"), "tenant_id": case["tenant_id"], "case_id": case_id, "gate": "G1",
                                        "approver_id": actor.user_id, "decision": decision, "conditions": [], "rationale": rationale, "decided_at": iso(now())})
        self.store.audit(case["tenant_id"], actor.user_id, "human", f"G1_{decision}", "screening", screening_id,
                         {"subject": row["subject_name"], "match": row["match_name"], "score": row["score"], "rationale": rationale})
        return self.advance(case_id)

    # Emergency conditional approval (GX): head of TPRM only, sanctions must be resolved, <=30 days.
    @case_locked
    def request_emergency(self, actor: Actor, case_id: str, d: GateDecision) -> dict:
        case = self._scoped(case_id, actor)
        self.policy.check_gate_actor("GX", case["final_tier"], actor.role)
        if not case["emergency"]:
            raise PolicyError("E_EMERGENCY", "case was not raised as an emergency")
        if case["state"] not in EMERGENCY_FROM:
            raise PolicyError("E_EMERGENCY", f"emergency approval is not available in state {case['state']}")
        self.policy.check_screening_to_tiering(screening_agent.unresolved(self.svc, case_id))
        if d.decision != "APPROVE" or not d.expires_at:
            raise PolicyError("E_EMERGENCY", "GX needs decision=APPROVE and expires_at (<=30 days)")
        exp = parse_date(d.expires_at)
        self.policy.check_conditional_expiry((exp - now().date()).days)
        self.policy.check_sod(actor.user_id, case["requester_id"], case["preparer_id"])
        self._decide(case, "GX", actor, d)
        self.store.update("cases", "case_id", case_id, {"conditional_expires": iso(exp)})
        self.store.update("vendor", "vendor_id", case["vendor_id"], {"status": "CONDITIONAL", "updated_at": iso(now())})
        self._ctx(case, emergency_approved=True)
        return self.advance(case_id)

    # ------------------------------------------------------------------ findings / questions / feedback
    @case_locked
    def disposition_finding(self, actor: Actor, case_id: str, finding_id: str, action: str, rationale: str, expires_at: str | None = None) -> dict:
        case = self._scoped(case_id, actor)
        f = self.store.one("SELECT * FROM findings WHERE finding_id=? AND case_id=?", (finding_id, case_id))
        if not f:
            raise NotFound(finding_id)
        if action not in ("REMEDIATED", "ACCEPT_RISK"):
            raise PolicyError("E_DECISION", "finding disposition must be REMEDIATED or ACCEPT_RISK")
        if actor.role not in ("analyst", "senior_analyst", "infosec", "legal", "senior_risk", "committee", "manager"):
            raise PolicyError("E_ROLE", "role cannot disposition findings")
        if action == "ACCEPT_RISK":
            if f["severity"] in ("CRITICAL", "HIGH") and actor.role not in ("senior_risk", "committee"):
                raise PolicyError("E_ROLE", "accepting a HIGH/CRITICAL risk needs senior_risk or committee")
            if not expires_at or not parse_date(expires_at) or parse_date(expires_at) <= now().date():
                raise PolicyError("E_EXCEPTION_EXPIRY", "a risk exception needs a future expiry date")
        if len(rationale.strip()) < 10:
            raise PolicyError("E_RATIONALE", "a disposition needs a written rationale")
        self.store.update("findings", "finding_id", finding_id, {"disposition": action, "disposition_by": actor.user_id, "exception_expires": expires_at})
        self.store.audit(case["tenant_id"], actor.user_id, "human", f"FINDING_{action}", "finding", finding_id, {"rationale": rationale, "expires_at": expires_at})
        return self.store.get("findings", "finding_id", finding_id)

    @case_locked
    def dispute_finding(self, actor: Actor, case_id: str, finding_id: str, reason: str) -> dict:
        case = self._scoped(case_id, actor)
        f = self.store.one("SELECT * FROM findings WHERE finding_id=? AND case_id=?", (finding_id, case_id))
        if not f:
            raise NotFound(finding_id)
        self.store.update("findings", "finding_id", finding_id, {"disputed": 1, "disputed_by": actor.user_id, "disputed_reason": reason})
        self.store.insert("feedback", {"feedback_id": new_id("fb_"), "tenant_id": case["tenant_id"], "case_id": case_id, "kind": "finding_dispute",
                                       "ref": finding_id, "note": reason, "user": actor.user_id, "created_at": iso(now())})
        self.store.audit(case["tenant_id"], actor.user_id, "human", "FINDING_DISPUTED", "finding", finding_id, {"reason": reason})
        return self.store.get("findings", "finding_id", finding_id)

    @case_locked
    def answer_question(self, actor: Actor, case_id: str, question_id: str, answer: str) -> dict:
        case = self._scoped(case_id, actor)
        q = self.store.one("SELECT * FROM questions WHERE question_id=? AND case_id=?", (question_id, case_id))
        if not q:
            raise NotFound(question_id)
        self.store.update("questions", "question_id", question_id, {"status": "ANSWERED", "answer": answer, "answered_by": actor.user_id})
        self.store.audit(case["tenant_id"], actor.user_id, "human", "QUESTION_ANSWERED", "question", question_id, {})
        return self.store.get("questions", "question_id", question_id)

    @case_locked
    def proceed_with_gaps(self, actor: Actor, case_id: str) -> dict:
        case = self._scoped(case_id, actor)
        if actor.role not in ("analyst", "senior_analyst"):
            raise PolicyError("E_ROLE", "only analysts may proceed with documented gaps")
        self._ctx(case, proceed_with_gaps=True)
        self.store.audit(case["tenant_id"], actor.user_id, "human", "PROCEED_WITH_GAPS", "case", case_id, {"missing": self.missing_docs(case)})
        return self.advance(case_id)

    @case_locked
    def hold(self, actor: Actor, case_id: str, reason: str) -> dict:
        case = self._scoped(case_id, actor)
        self._to(case, "ON_HOLD", actor.user_id, reason)
        self.store.update("cases", "case_id", case_id, {"hold_reason": reason})
        return self.case(case_id)

    @case_locked
    def resume(self, actor: Actor, case_id: str, to: str = "DUE_DILIGENCE") -> dict:
        case = self._scoped(case_id, actor)
        self._to(case, to, actor.user_id, "resumed")
        return self.advance(case_id)

    # ------------------------------------------------------------------ continuous monitoring / sweeps
    @case_locked
    def material_change(self, actor: Actor, case_id: str, kind: str) -> dict:
        case = self._scoped(case_id, actor)
        self.svc.ledger.on_material_change(case["tenant_id"], case["vendor_id"], kind)
        if case["state"] in ("MONITORING", "HUMAN_REVIEW", "VERIFICATION"):
            self._close_task(case_id, "G3", "system")
            self._to(case, "ASSESSMENT", "system:workflow", f"material change: {kind}")
        self.store.audit(case["tenant_id"], actor.user_id, "human", "MATERIAL_CHANGE", "case", case_id, {"kind": kind})
        return self.advance(case_id)

    def rescreen_active(self, tenant_id: str) -> list[str]:
        """Sanctions list updated (webhook): ST-004 stales prior screening conclusions; open cases are re-screened."""
        out = []
        for c in self.store.query("SELECT * FROM cases WHERE tenant_id=? AND state IN ('SCREENING','HUMAN_SCREEN_REVIEW','TIERING','DUE_DILIGENCE','ASSESSMENT','VERIFICATION','HUMAN_REVIEW','CONTRACTING','FINAL_APPROVAL','MONITORING','ONBOARDED')", (tenant_id,)):
            screening_agent.run(self.svc, c)
            if screening_agent.unresolved(self.svc, c["case_id"]) > 0 and c["state"] in ("MONITORING", "ONBOARDED"):
                self._open_task(c, "G1", {"reason": "list update"})
                out.append(c["case_id"])
        return out

    def sweep(self, tenant_id: str) -> dict:
        """Scheduled job: staleness (A11), conditional approval expiry, SLA breaches."""
        stale = steward.sweep(self.svc, tenant_id)
        expired = []
        for c in self.store.query("SELECT * FROM cases WHERE tenant_id=? AND conditional_expires IS NOT NULL AND state NOT IN ('MONITORING','REJECTED','CLOSED')", (tenant_id,)):
            if (parse_date(c["conditional_expires"]) or now().date()) < now().date():
                self.store.update("vendor", "vendor_id", c["vendor_id"], {"status": "SUSPENDED", "updated_at": iso(now())})
                self.store.audit(tenant_id, "system:workflow", "system", "CONDITIONAL_EXPIRED", "case", c["case_id"], {})
                expired.append(c["case_id"])
        overdue = [t["task_id"] for t in self.store.query("SELECT * FROM gate_tasks WHERE tenant_id=? AND status='OPEN'", (tenant_id,))
                   if (parse_date(t["due_at"][:10]) or now().date()) < now().date()]
        return {"stale": len(stale), "conditional_expired": expired, "sla_overdue": overdue}
