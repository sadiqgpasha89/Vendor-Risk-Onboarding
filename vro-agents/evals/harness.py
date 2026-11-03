"""Drives a synthetic scenario through the real workflow with simulated humans (analyst, AML, senior analyst, approvers).
Used by the eval runner and the integration tests. Humans here follow the scenario's expected outcome; agents never decide."""
from __future__ import annotations

import json
from pathlib import Path

from vro.agents.services import Services
from vro.models import GateDecision
from vro.policy import PolicyError
from vro.workflow import Actor, Workflow

ROOT = Path(__file__).resolve().parent.parent
SYN = ROOT / "data" / "synth"
TENANT = "t_demo"
SPONSOR = Actor("u_sponsor", "sponsor", TENANT)
ANALYST = Actor("u_analyst", "analyst", TENANT)
SENIOR = Actor("u_senior", "senior_analyst", TENANT)
AML = Actor("u_aml", "aml", TENANT)
APPROVERS = {1: Actor("u_committee", "committee", TENANT), 2: Actor("u_srisk", "senior_risk", TENANT),
             3: Actor("u_manager", "manager", TENANT), 4: Actor("u_manager", "manager", TENANT)}


def load(key: str) -> tuple[dict, dict, dict[str, bytes]]:
    base = SYN / "vendors" / key
    intake = json.loads((base / "intake.json").read_text())
    expected = json.loads((base / "expected.json").read_text())
    docs = {p.name: p.read_bytes() for p in sorted((base / "docs").glob("*")) if p.is_file()}
    return intake, expected, docs


def drive(svc: Services, wf: Workflow, key: str, *, finish: bool = True, intake_patch: dict | None = None, extra_docs: dict | None = None,
          docs_override: dict | None = None) -> dict:
    intake, expected, docs = load(key)
    if docs_override is not None:
        docs = docs_override
    if intake_patch:
        intake = {**intake, **intake_patch}
    case = wf.create_case(SPONSOR, intake)
    cid = case["case_id"]
    log = {"key": key, "case_id": cid, "uploads": {}, "errors": []}
    for name, data in {**docs, **(extra_docs or {})}.items():
        log["uploads"][name] = wf.upload_document(ANALYST, cid, name, data)
    for _ in range(12):
        case = wf.case(cid)
        st = case["state"]
        if st == "INTAKE_REVIEW" and wf._task(cid, "G0"):
            wf.decide_gate(ANALYST, cid, "G0", GateDecision(decision="REJECT", rationale="different legal entity"))
        elif st == "HUMAN_SCREEN_REVIEW":
            for r in svc.store.query("SELECT * FROM screening_results WHERE case_id=? AND auto_disposition='POTENTIAL_MATCH' AND human_disposition IS NULL", (cid,)):
                dec = "CONFIRM_MATCH" if expected.get("aml") == "confirm" else "CLEAR"
                wf.decide_screening(AML, cid, r["screening_id"], dec, "simulated AML disposition per scenario ground truth")
        elif st == "TIERING":
            wf.decide_gate(SENIOR, cid, "G2", GateDecision(decision="CONFIRM", rationale="agree with proposed tier"))
        elif st == "DUE_DILIGENCE":
            wf.proceed_with_gaps(ANALYST, cid)
        elif st == "HUMAN_REVIEW":
            if not finish:
                break
            try:
                wf.decide_gate(ANALYST, cid, "G3", GateDecision(decision="APPROVE", rationale="findings reviewed"))
            except PolicyError as e:
                log["errors"].append(e.code)
                break
        elif st == "CONTRACTING":
            wf.complete_contracting(ANALYST, cid)
        elif st == "FINAL_APPROVAL":
            tier = case["final_tier"] or 2
            try:
                wf.decide_gate(APPROVERS[tier], cid, "G4", GateDecision(decision="APPROVE", rationale="approved after review"))
            except PolicyError as e:
                log["errors"].append(e.code)
                break
        else:
            break
    case = wf.case(cid)
    log.update(summarise(svc, case), expected=expected)
    return log


def summarise(svc: Services, case: dict) -> dict:
    cid = case["case_id"]
    q = svc.store.query
    fnd = q("SELECT severity, rule_id, title, domain FROM findings WHERE case_id=? AND status='OPEN'", (cid,))
    claims = q("SELECT status, COUNT(*) n FROM claims WHERE vendor_id=? GROUP BY status", (case["vendor_id"],))
    a = svc.store.one("SELECT * FROM assessments WHERE case_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (cid,))
    return {"state": case["state"], "proposed_tier": case["proposed_tier"], "final_tier": case["final_tier"],
            "rules": sorted({f["rule_id"] for f in fnd if f["rule_id"]}), "findings": fnd,
            "claims": {r["status"]: r["n"] for r in claims}, "band": (a or {}).get("residual", {}).get("band") if a else None,
            "residual": (a or {}).get("residual"), "narrative": (a or {}).get("narrative"),
            "screen_potential": [r["subject_name"] for r in q("SELECT subject_name FROM screening_results WHERE case_id=? AND auto_disposition='POTENTIAL_MATCH'", (cid,))]}
