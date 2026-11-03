"""A3 Tiering: deterministic inherent-risk score -> proposed tier. The score is computed by code (R1); a human confirms (G2)."""
from __future__ import annotations

from ..models import VendorIntake
from .runtime import run_agent
from .services import Services


def run(svc: Services, case: dict) -> dict:
    intake = VendorIntake.model_validate(case["intake"])

    def work(run_id: str) -> dict:
        tp = svc.scoring.inherent(intake)
        svc.store.update("cases", "case_id", case["case_id"], {"proposed_tier": tp.tier})
        return tp.model_dump()

    return run_agent(svc, case, "A3", {"intake": intake.model_dump(), "scoring": svc.scoring.version}, work)
