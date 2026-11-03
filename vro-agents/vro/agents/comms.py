"""A12 Comms Drafter: drafts only. There is no send tool anywhere in the system (R3, GR-011)."""
from __future__ import annotations

from .services import Services


def draft_document_request(svc: Services, case: dict, missing: list[str]) -> str | None:
    if not missing:
        return None
    ctx = svc.new_ctx(case, "A12", "comms")
    r = ctx.call("draft_comms", kind="document_request", context={"vendor": case["intake"]["legal_name"], "missing_docs": missing,
                                                               "owner": case["intake"].get("business_owner")})
    return r["draft_id"]


def draft_remediation(svc: Services, case: dict, findings: list[dict]) -> str | None:
    if not findings:
        return None
    ctx = svc.new_ctx(case, "A12", "comms")
    r = ctx.call("draft_comms", kind="remediation_request", context={"vendor": case["intake"]["legal_name"], "findings": [
        {"severity": f["severity"], "title": f["title"], "remediation": f.get("remediation")} for f in findings]})
    return r["draft_id"]
