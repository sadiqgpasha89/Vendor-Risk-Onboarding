"""A1 Intake & Entity Resolution: normalise intake, record ownership edges, link to the vendor master (G0 if uncertain)."""
from __future__ import annotations

from ..models import Question, VendorIntake
from ..screening import resolve_entity
from ..util import iso, new_id, now
from .runtime import run_agent
from .services import Services


def run(svc: Services, case: dict) -> dict:
    intake = VendorIntake.model_validate(case["intake"])
    master = svc.store.query("SELECT * FROM vendor WHERE tenant_id=? AND vendor_id<>?", (case["tenant_id"], case["vendor_id"]))

    def work(run_id: str) -> dict:
        res = resolve_entity(intake.model_dump(), master)
        svc.store.execute("DELETE FROM ownership_edge WHERE case_id=?", (case["case_id"],))
        for o in intake.declared_owners:
            svc.store.insert("ownership_edge", {"edge_id": new_id("oe_"), "tenant_id": case["tenant_id"], "case_id": case["case_id"],
                                                "child_name": intake.legal_name, "parent_name": o.name, "pct": o.pct,
                                                "is_person": o.is_person, "country_iso2": o.country_iso2, "source": "declared",
                                                "as_of": iso(now().date())})
        questions = []
        if not intake.declared_owners:
            questions.append(Question(to_role="sponsor", text="Please obtain the vendor's ownership declaration (holders of 25% or more).",
                                      why_it_matters="Beneficial ownership cannot be screened without it.", blocking=False))
        for q in questions:
            svc.store.insert("questions", {"question_id": new_id("q_"), "tenant_id": case["tenant_id"], "case_id": case["case_id"],
                                           "to_role": q.to_role, "text": q.text, "why": q.why_it_matters, "blocking": q.blocking,
                                           "options": None, "status": "OPEN", "created_at": iso(now())})
        return {"resolution": res, "questions": len(questions)}

    return run_agent(svc, case, "A1", {"intake": intake.model_dump(), "master": [m["vendor_id"] for m in master]}, work)
