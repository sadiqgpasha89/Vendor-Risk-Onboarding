"""A10 independent Verifier. Receives ONLY claims + fetched evidence passages (no author rationale, no confidence). Mirrors §7.6/§9."""
from __future__ import annotations

from ..llm_gateway import LLMRequest
from ..util import now
from .prompts import VERIFIER, system_for
from .runtime import run_agent
from .services import Services

BAD = {"UNSUPPORTED", "CONTRADICTED", "OVERSTATED"}


def build_items(svc: Services, claims: list[dict]) -> list[dict]:
    items = []
    for c in claims:
        evs = []
        for e in svc.ledger.evidence(c["claim_id"]):
            d = svc.store.get("documents", "doc_id", e["doc_id"]) if e["doc_id"] else None
            evs.append({"quote": e["quote"], "locator": e["locator"], "source_kind": "document" if e["source_type"] == "document" else e["source_type"],
                        "pages": (d["clean_text"] or "").split("\f") if d else [], "doc_text": (d["clean_text"] or "") if d else ""})
        items.append({"claim_id": c["claim_id"], "subject": c["subject"], "statement": c["statement"], "predicate": c["predicate"], "object": c["object"], "evidence": evs})
    return items


def run(svc: Services, case: dict) -> dict:
    claims = svc.ledger.get_claims(case["tenant_id"], case["vendor_id"], status="UNTRUSTED")
    if not claims:
        return {"verified": 0, "refuted": 0, "partial": 0, "total": 0}
    items = build_items(svc, claims)

    def work(run_id: str) -> dict:
        req = LLMRequest(task="verifier.verify", system=system_for("A10 Verifier", VERIFIER, today=now().date(), policy_version=svc.policy.version,
                                                                    tenant_id=case["tenant_id"], case_id=case["case_id"]),
                         user="verify", tier="large", agent="A10", case_id=case["case_id"], context={"items": items})
        verdicts = svc.gateway.complete(req).data["verdicts"]
        n_ok = n_bad = n_part = 0
        for v in verdicts:
            if v["verdict"] == "SUPPORTED":
                svc.ledger.set_status(v["claim_id"], "TRUSTED", "A10:verifier", "independent verification: SUPPORTED")
                n_ok += 1
            elif v["verdict"] in BAD:
                svc.ledger.set_status(v["claim_id"], "REFUTED", "A10:verifier", f"{v['verdict']}: {v.get('defect')}")
                n_bad += 1
            else:
                n_part += 1
        return {"verified": n_ok, "refuted": n_bad, "partial": n_part, "total": len(verdicts), "verdicts": verdicts}

    return run_agent(svc, case, "A10", [i["claim_id"] for i in items], work)
