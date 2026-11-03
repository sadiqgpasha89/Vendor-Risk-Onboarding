"""A4 Reader: extracts structured fields from ONE untrusted document. It has NO tools (GR-008) and returns schema-only JSON.
`extraction_to_claims` converts the extraction into atomic, evidence-bearing claims (R2) with the predicate names the rules use."""
from __future__ import annotations

from ..llm_gateway import LLMRequest
from ..models import Claim, DocExtraction, Evidence
from ..util import iso, now, parse_date
from .prompts import READER_GENERIC, READER_SOC2, system_for, untrusted_block
from .runtime import persist_result, run_agent
from .services import Services
from ..models import AgentResult

# doc_type -> {extracted field name -> (predicate, statement template)}
FIELD_MAP = {
    "soc2_report": {"report_type": ("soc2_report_type", "SOC 2 report type is {v}"), "opinion": ("soc2_opinion", "The SOC 2 auditor's opinion is {v}"),
                    "period_start": ("soc2_period_start", "SOC 2 review period starts {v}"), "period_end": ("soc2_period_end", "SOC 2 review period ends {v}")},
    "iso_certificate": {"valid_until": ("iso27001_valid_until", "ISO 27001 certificate is valid until {v}")},
    "insurance_certificate": {"cyber_limit_usd": ("insurance_cyber_limit_usd", "Cyber insurance limit is USD {v}"),
                              "valid_until": ("insurance_valid_until", "Insurance coverage is valid until {v}"),
                              "named_insured": ("insurance_named_insured", "Named insured on the certificate is {v}")},
    "pentest_summary": {"test_date": ("pentest_date", "Penetration test was performed on {v}"),
                        "unresolved_critical": ("pentest_unresolved_critical", "{v} critical penetration-test finding(s) are unresolved"),
                        "scope_includes_production": ("pentest_scope_includes_production", "Penetration test scope includes production: {v}")},
    "bcp_dr": {"rto_hours": ("bcp_rto_hours", "Recovery time objective is {v} hours"), "dr_last_tested": ("bcp_dr_last_tested", "Last DR test: {v}"),
               "regions": ("bcp_regions", "Operating regions: {v}")},
    "contract": {"breach_notice_hours": ("contract_breach_notice_hours", "Contract requires breach notice within {v} hours"),
                 "liability_cap_multiple": ("contract_liability_cap_multiple", "Liability is capped at {v}x annual fees")},
    "dpa": {"subprocessors_listed": ("dpa_subprocessors_listed", "The DPA lists sub-processors: {v}"),
            "transfer_mechanism": ("dpa_transfer_mechanism", "Cross-border transfer mechanism in the DPA: {v}")},
    "financial_statements": {"going_concern_doubt": ("financial_going_concern_doubt", "Going-concern doubt is stated: {v}"),
                             "total_equity_usd": ("financial_total_equity_usd", "Total equity is USD {v}"),
                             "current_ratio": ("financial_current_ratio", "Current ratio is {v}"),
                             "revenue_concentration_pct": ("financial_revenue_concentration_pct", "Largest customer is {v}% of revenue")},
}


def extraction_to_claims(ex: DocExtraction, doc: dict, vendor: str) -> list[Claim]:
    def ev(page, quote, locator=None):
        return Evidence(source_type="document", doc_id=doc["doc_id"], page=page, quote=quote, locator=locator, source_sha256=doc["sha256"])

    out: list[Claim] = []
    for f in ex.fields:
        m = FIELD_MAP.get(ex.doc_type, {}).get(f.name)
        if not m or not f.found or f.value is None or not f.quote:
            continue
        pred, tmpl = m
        out.append(Claim(subject=vendor, predicate=pred, object=f.value, statement=tmpl.format(v=f.value), confidence=0.9, evidence=[ev(f.page, f.quote)]))
    L = ex.lists
    if ex.doc_type == "soc2_report":
        for s in L.get("in_scope", []):
            pass
        for r in L.get("out_of_scope", []):
            out.append(Claim(subject=f"{vendor} / {r['service']}", predicate="soc2_service_excluded", object=r["service"],
                             statement=f"The SOC 2 report excludes the service '{r['service']}' from scope", confidence=0.85, evidence=[ev(r["page"], r["quote"])]))
        for r in L.get("subservice_orgs", []):
            if r["method"] == "carve-out":
                out.append(Claim(subject=vendor, predicate="soc2_subservice_carved_out", object=r["name"],
                                 statement=f"Subservice organisation {r['name']} is carved out of the SOC 2 scope", confidence=0.85, evidence=[ev(r["page"], r["quote"])]))
        for r in L.get("exceptions", []):
            out.append(Claim(subject=f"{vendor} / {r['control_id']}", predicate="soc2_exception", object={"control_id": r["control_id"], "description": r["description"]},
                             statement=f"The SOC 2 report notes an exception for control {r['control_id']}: {r['description']}", confidence=0.85, evidence=[ev(r["page"], r["quote"])]))
        for i, r in enumerate(L.get("cuecs", [])):
            out.append(Claim(subject=f"{vendor} / CUEC {i + 1}", predicate="soc2_cuec", object=r["text"],
                             statement=f"Complementary user-entity control: {r['text']}", confidence=0.8, evidence=[ev(r["page"], r["quote"])]))
        for f in ex.fields:
            if f.name == "in_scope_services" and f.found and isinstance(f.value, list):
                for svc_name in f.value:
                    out.append(Claim(subject=f"{vendor} / {svc_name}", predicate="soc2_service_in_scope", object=svc_name,
                                     statement=f"The SOC 2 report covers the service '{svc_name}'", confidence=0.85, evidence=[ev(f.page, f.quote)]))
    if ex.doc_type == "contract":
        for c in L.get("clauses", []):
            present = bool(c["present"])
            out.append(Claim(subject=f"{vendor} / {c['clause']}", predicate="contract_clause_present", object=present,
                             statement=(f"The contract contains a {c['clause'].replace('_', ' ')} clause" if present
                                        else f"The contract does not contain a {c['clause'].replace('_', ' ')} clause"),
                             confidence=0.8, evidence=[ev(c["page"], c["quote"], None if present else f"absence:{c['clause']}")]))
    return out


def run_for_doc(svc: Services, case: dict, doc: dict) -> dict:
    pages = (doc["clean_text"] or "").split("\f")
    tainted = bool(doc.get("injection_flags"))
    # (re)index for retrieval - cheap and idempotent
    svc.retrieval.index_document(case["tenant_id"], case["vendor_id"], doc["doc_id"], doc["doc_type"], pages, doc.get("ocr_quality") or "high")

    def work(run_id: str) -> dict:
        body = READER_SOC2 if doc["doc_type"] == "soc2_report" else READER_GENERIC.format(doc_type=doc["doc_type"])
        req = LLMRequest(task="reader.extract", system=system_for("A4 Reader", body, today=now().date(), policy_version=svc.policy.version,
                                                                   tenant_id=case["tenant_id"], case_id=case["case_id"]),
                         user=untrusted_block(doc["doc_id"], pages), tier="mid", agent="A4", case_id=case["case_id"],
                         context={"doc_id": doc["doc_id"], "doc_type": doc["doc_type"], "pages": pages, "had_injection": tainted})
        ex = svc.gateway.structured(req, DocExtraction)
        vendor = case["intake"]["legal_name"]
        claims = extraction_to_claims(ex, doc, vendor)
        res = AgentResult(status="OK" if claims else "INSUFFICIENT_EVIDENCE", claims=claims, flags=ex.flags, confidence=0.9 if claims else 0.0)
        p = persist_result(svc, case, "A4", res)
        svc.store.update("documents", "doc_id", doc["doc_id"], {"processed": 1})
        return {"doc_id": doc["doc_id"], "doc_type": doc["doc_type"], "claims": len(p["claim_ids"]), "dropped": len(p["dropped"]), "flags": ex.flags}

    return run_agent(svc, case, "A4", {"doc": doc["doc_id"], "sha": doc["sha256"]}, work)


def run(svc: Services, case: dict) -> list[dict]:
    out = []
    for d in svc.current_docs(case["tenant_id"], case["vendor_id"]):
        if not d.get("processed"):
            out.append(run_for_doc(svc, case, d))
    return out
