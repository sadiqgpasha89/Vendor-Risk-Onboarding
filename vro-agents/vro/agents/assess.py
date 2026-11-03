"""A5-A8 specialists: LLM-free deterministic analysis over claims (R1). A9 synthesizer narrative. Persists findings + assessment."""
from __future__ import annotations

from ..analysis.rules import SPECIALISTS, Facts, Out, document_integrity
from ..llm_gateway import LLMRequest
from ..models import Evidence, VendorIntake
from ..util import canonical_json, iso, new_id, now, sha256_text
from ..validators import language_safety
from .prompts import PROMPT_VERSION, SYNTH, system_for
from .services import Services

SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


def make_gap_claim(svc: Services, case: dict):
    def gap(predicate: str, subject: str, statement: str, obj) -> str:
        from ..models import Claim
        inv = svc.doc_inventory(case["tenant_id"], case["vendor_id"])
        sha = sha256_text(canonical_json(sorted(d["sha256"] for d in inv)))
        c = Claim(subject=subject, predicate=predicate, object=obj, statement=statement, confidence=1.0,
                  evidence=[Evidence(source_type="api", locator=f"inventory:{predicate}", source_sha256=sha, quote=None)])
        return svc.ledger.create_claim(case["tenant_id"], case["vendor_id"], case["case_id"], c, "system:policy", PROMPT_VERSION, status="TRUSTED")
    return gap


def assess(svc: Services, case: dict, mode: str = "final", portfolio: bool = True) -> dict:
    """mode='provisional' uses all active claims (pre-verification); mode='final' uses TRUSTED claims only (R2/§9)."""
    case = svc.case(case["case_id"])
    tier = case["final_tier"] or case["proposed_tier"] or 2
    plan = svc.policy.plan(tier, case["jurisdictions"] or [])
    if mode == "final":
        claims = svc.ledger.trusted(case["tenant_id"], case["vendor_id"])
    else:
        claims = [c for c in svc.ledger.get_claims(case["tenant_id"], case["vendor_id"], with_evidence=True)]
        for c in claims:
            c["evidence"] = c.get("evidence") or svc.ledger.evidence(c["claim_id"])
    facts = Facts(claims=claims, docs=svc.current_docs(case["tenant_id"], case["vendor_id"]), intake=case["intake"], plan=plan, policy=svc.policy,
                  today=now().date(), tier=tier, gap_claim=make_gap_claim(svc, case),
                  portfolio=svc.portfolio_intakes(case["tenant_id"], case["case_id"]) if portfolio else [])
    # a gap claim created during this pass must be visible to later rules in the same pass, so rules take claim ids from gap_claim directly
    out = Out()
    wanted = list(plan["specialists"])
    ran = []
    for agent in ("A5", "A6", "A7", "A8"):
        if agent in wanted:
            ran.append(agent)
            for rule in SPECIALISTS[agent]:
                out.merge(rule(facts))
    if "A8" not in wanted:
        out.merge(document_integrity(facts))
    findings = sorted(out.findings, key=lambda f: SEV_ORDER[f.severity])
    # carry over human disputes/dispositions for identical findings, then supersede the previous pass
    prior = svc.store.query("SELECT * FROM findings WHERE case_id=? AND status='OPEN'", (case["case_id"],))
    carry = {(p["rule_id"], tuple(sorted(p["claim_ids"] or []))): p for p in prior}
    svc.store.execute("UPDATE findings SET status='SUPERSEDED' WHERE case_id=? AND status='OPEN'", (case["case_id"],))
    persisted = []
    for f in findings:
        p = carry.get((f.rule_id, tuple(sorted(f.claim_ids))))
        fid = new_id("f_")
        svc.store.insert("findings", {
            "finding_id": fid, "tenant_id": case["tenant_id"], "case_id": case["case_id"], "domain": f.domain, "severity": f.severity,
            "title": f.title, "description": f.description, "claim_ids": f.claim_ids, "regulation_refs": f.regulation_refs,
            "remediation": f.remediation, "status": "OPEN", "rule_id": f.rule_id, "created_at": iso(now()),
            "disputed": (p or {}).get("disputed", 0), "disputed_by": (p or {}).get("disputed_by"), "disputed_reason": (p or {}).get("disputed_reason"),
            "disposition": (p or {}).get("disposition"), "disposition_by": (p or {}).get("disposition_by"),
            "exception_expires": (p or {}).get("exception_expires")})
        persisted.append(fid)
    ce = svc.scoring.control_effectiveness(out.checks)
    inh = svc.scoring.inherent(VendorIntake.model_validate(case["intake"]))
    res = svc.scoring.residual(inh.inherent_score, ce, [f.severity for f in findings if not _excepted(svc, f, case)])
    missing = [d for d in plan["required_docs"] if not facts.doc(d)]
    unverified = len([c for c in svc.ledger.get_claims(case["tenant_id"], case["vendor_id"]) if c["status"] == "UNTRUSTED"])
    narrative = _narrative(svc, case, tier, inh.inherent_score, res, findings, unverified, missing)
    aid = new_id("as_")
    svc.store.insert("assessments", {"assessment_id": aid, "tenant_id": case["tenant_id"], "case_id": case["case_id"], "scoring_version": svc.scoring.version,
                                     "inherent": inh.model_dump(), "control_effectiveness": ce, "residual": {**res, "mode": mode}, "tier": tier,
                                     "overrides": None, "narrative": narrative, "created_at": iso(now())})
    svc.store.audit(case["tenant_id"], "A5-A9", "agent", f"ASSESSMENT_{mode.upper()}", "case", case["case_id"],
                    {"assessment_id": aid, "band": res["band"], "findings": len(findings), "specialists": ran})
    return {"assessment_id": aid, "residual": res, "findings": len(findings), "finding_ids": persisted, "missing_docs": missing,
            "unverified": unverified, "specialists": ran}


def _excepted(svc, f, case) -> bool:
    return False


def _narrative(svc: Services, case: dict, tier: int, inherent: float, res: dict, findings, unverified: int, missing: list[str]) -> str:
    req = LLMRequest(task="synth.narrative", system=system_for("A9 Synthesizer", SYNTH, today=now().date(), policy_version=svc.policy.version,
                                                              tenant_id=case["tenant_id"], case_id=case["case_id"]),
                     user=canonical_json({"tier": tier, "residual": res, "top": [f.title for f in findings[:5]]}), tier="mid", agent="A9",
                     case_id=case["case_id"], context={"band": res["band"], "residual_score": res["residual_score"], "inherent_score": inherent, "tier": tier,
                                                       "top_findings": [{"title": f.title, "severity": f.severity} for f in findings[:5]],
                                                       "unverified": unverified, "missing_docs": missing})
    txt = svc.gateway.complete(req).data["narrative"]
    return language_safety(txt)[0]
