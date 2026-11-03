"""A2 Screening Adjudicator: runs the deterministic matcher and records a RECOMMENDATION. It never clears a match (R3, GR-001)."""
from __future__ import annotations

from ..util import iso, new_id, now
from ..screening import screen_case
from .runtime import run_agent
from .services import Services


def recommend(rec: dict) -> tuple[str, str]:
    """Rules-based triage hint for the AML analyst. Conservative: only NEEDS_HUMAN / LIKELY_* ; never 'clear'."""
    if rec["auto_disposition"] == "NO_CANDIDATE":
        return "NO_CANDIDATE", rec["explanation"]
    f = rec.get("features") or {}
    s = rec["score"]
    if rec["subject_role"] == "ownership_aggregate":
        return "NEEDS_HUMAN", rec["explanation"]
    if s >= 0.95 and f.get("country", 0) >= 1.0:
        return "LIKELY_TRUE_MATCH", rec["explanation"]
    if s < 0.88 and f.get("country", 1) == 0.0:
        return "LIKELY_FALSE_POSITIVE", rec["explanation"] + " Country differs from the list entry; a human must still disposition."
    return "NEEDS_HUMAN", rec["explanation"]


def run(svc: Services, case: dict) -> dict:
    intake = dict(case["intake"])
    edges = svc.store.query("SELECT * FROM ownership_edge WHERE case_id=?", (case["case_id"],))

    def work(run_id: str) -> dict:
        results = screen_case(intake, edges, svc.sanctions, svc.settings.review_floor)
        svc.store.execute("DELETE FROM screening_results WHERE case_id=? AND human_disposition IS NULL", (case["case_id"],))
        n_pot = 0
        for r in results:
            rc, expl = recommend(r)
            n_pot += r["auto_disposition"] == "POTENTIAL_MATCH"
            svc.store.insert("screening_results", {
                "screening_id": new_id("sc_"), "tenant_id": case["tenant_id"], "case_id": case["case_id"], "subject_name": r["subject_name"],
                "subject_role": r["subject_role"], "list_name": r["list_name"], "list_version": r["list_version"],
                "match_entity_id": r["match_entity_id"], "match_name": r["match_name"], "score": r["score"],
                "features": {**(r.get("features") or {}), "ownership_pct": r.get("ownership_pct"), "program": r.get("program")},
                "auto_disposition": r["auto_disposition"], "recommendation": rc, "explanation": expl, "created_at": iso(now())})
        return {"subjects": len(results), "potential_matches": n_pot, "list_version": svc.sanctions.version}

    return run_agent(svc, case, "A2", {"intake": intake, "edges": [(e["parent_name"], e["pct"]) for e in edges],
                                       "list": svc.sanctions.version}, work)


def unresolved(svc: Services, case_id: str) -> int:
    row = svc.store.one("SELECT COUNT(*) n FROM screening_results WHERE case_id=? AND auto_disposition='POTENTIAL_MATCH' AND human_disposition IS NULL", (case_id,))
    return int(row["n"])
