"""Offline task handlers for RulesProvider. This is a deterministic, rule-based BASELINE, not a language model.

It exists so the full pipeline runs, tests and evals without network access, and as the regression baseline an LLM provider
must beat (plan §6.3.4/§7). Real vendor documents vary far more than these patterns cover; with LLM_PROVIDER=anthropic the
same task names go to a model and the same validators (schema -> citation -> numeric -> language) police the answer.

Tasks:
  reader.extract    -> DocExtraction JSON for ONE document (A4: no tools, schema-only output)
  verifier.verify   -> per-claim verdicts from claims + system-fetched evidence passages ONLY (A10 independence)
  synth.narrative   -> assessment narrative from already-computed structured results (numbers never invented)
  comms.draft       -> vendor request / remediation draft text (drafts only, GR-011)
  specialist.review -> optional second look (offline: no additional findings)
"""
from __future__ import annotations

import re
from datetime import date, datetime

from .docproc import ANY_DATE, MONTHS, _to_date
from .quotes import locate_quote, norm

# ---------------------------------------------------------------------------- helpers
def _quote(line: str) -> str:
    return " ".join(line.split()[:40])


def _hit(pages: list[str], rx: re.Pattern):
    for pn, page in enumerate(pages, 1):
        for ln in page.split("\n"):
            m = rx.search(ln)
            if m:
                return pn, ln.strip(), m
    return None


def _para_hit(pages: list[str], rx: re.Pattern):
    for pn, page in enumerate(pages, 1):
        flat = " ".join(page.split())
        m = rx.search(flat)
        if m:
            return pn, flat[max(0, m.start() - 0): m.end()], m
    return None


def _field(name, value=None, hit=None):
    if hit is None or value is None:
        return {"name": name, "value": None, "found": False, "page": None, "quote": None}
    pn, line = hit[0], hit[1]
    return {"name": name, "value": value, "found": True, "page": pn, "quote": _quote(line)}


def _date_in(s: str) -> str | None:
    m = re.search(ANY_DATE, s, re.I)
    if not m:
        return None
    d = _to_date(m.group(1) or m.group(2))
    return d.isoformat() if d else None


def _money(s: str) -> float | None:
    m = re.search(r"\$?\s?(-?\(?[\d,]+(?:\.\d+)?\)?)\s*(million|m|bn|billion|k)?", s, re.I)
    if not m:
        return None
    raw = m.group(1)
    neg = raw.startswith("(") or raw.startswith("-")
    v = float(re.sub(r"[^\d.]", "", raw) or 0)
    mult = {"million": 1e6, "m": 1e6, "bn": 1e9, "billion": 1e9, "k": 1e3}.get((m.group(2) or "").lower(), 1)
    return -v * mult if neg else v * mult


def _split_list(s: str) -> list[str]:
    return [x.strip(" .;") for x in re.split(r"[;,]| and ", s) if x.strip(" .;")]


# ---------------------------------------------------------------------------- SOC 2
def extract_soc2(pages: list[str]) -> dict:
    F, L = [], {}
    h = _hit(pages, re.compile(r"\bType\s+(II|I|2|1)\b", re.I))
    if h:
        t = h[2].group(1).upper()
        F.append(_field("report_type", "Type II" if t in ("II", "2") else "Type I", h))
    else:
        F.append(_field("report_type"))
    h = _hit(pages, re.compile(r"(?:service\s+auditor|prepared\s+by|independent\s+service\s+auditor)\s*[:\-]\s*(.+)$", re.I))
    F.append(_field("service_auditor_name", h[2].group(1).strip() if h else None, h))
    # opinion: look at the sentence after "In our opinion"
    ph = _para_hit(pages, re.compile(r"In our opinion.{0,500}?\.", re.I))
    basis = _para_hit(pages, re.compile(r"(basis for (a )?qualified opinion|qualified opinion|except for the matter|adverse opinion|disclaimer of opinion|do not express an opinion)", re.I))
    opinion, ev = None, None
    if basis:
        b = basis[2].group(1).lower()
        ev = basis
        opinion = "adverse" if "adverse" in b else "disclaimer" if ("disclaimer" in b or "do not express" in b) else "qualified"
    elif ph:
        ev = ph
        opinion = "unqualified"
    F.append(_field("opinion", opinion, ev))
    h = _hit(pages, re.compile(r"(?:review|reporting|examination|audit)\s+period[^\n]*", re.I)) or _hit(pages, re.compile(r"period[^\n]*(?:to|through)[^\n]*"))
    ps = pe = None
    if h:
        ds = [d for d in (_date_in(x.group(0)) for x in re.finditer(ANY_DATE, h[1], re.I)) if d]
        if len(ds) >= 2:
            ps, pe = ds[0], ds[1]
    F.append(_field("period_start", ps, h)); F.append(_field("period_end", pe, h))
    h = _hit(pages, re.compile(r"(?:trust\s+services\s+categories|categories\s+in\s+scope)\s*[:\-]\s*(.+)$", re.I))
    F.append(_field("trust_services_categories", _split_list(h[2].group(1)) if h else None, h))
    h = _hit(pages, re.compile(r"in[- ]scope\s+services?\s*[:\-]\s*(.+)$", re.I))
    F.append(_field("in_scope_services", _split_list(h[2].group(1)) if h else None, h))
    ex_hits = []
    for pn, page in enumerate(pages, 1):
        for ln in page.split("\n"):
            m = re.search(r"(?:excluded\s+from\s+(?:the\s+)?scope(?:\s+of\s+this\s+report)?|out[- ]of[- ]scope(?:\s+services?)?|carved[- ]out\s+services?)\s*[:\-]\s*(.+)$", ln, re.I)
            if m:
                ex_hits.append((pn, ln.strip(), _split_list(m.group(1))))
    L["out_of_scope"] = [{"service": s, "page": pn, "quote": _quote(ln)} for pn, ln, svcs in ex_hits for s in svcs]
    L["subservice_orgs"] = []
    for pn, page in enumerate(pages, 1):
        for ln in page.split("\n"):
            m = re.search(r"sub-?service\s+organi[sz]ation\s*[:\-]\s*([^()\n]+?)\s*\(?\s*(carve-?out|inclusive)", ln, re.I)
            if m:
                L["subservice_orgs"].append({"name": m.group(1).strip(" ,-"), "method": "carve-out" if "carve" in m.group(2).lower() else "inclusive", "page": pn, "quote": _quote(ln)})
    L["exceptions"] = []
    for pn, page in enumerate(pages, 1):
        for ln in page.split("\n"):
            m = re.search(r"exception\s*(?:noted)?\s*[:\-]?\s*(?:control\s+)?([A-Z]{1,3}\d+(?:\.\d+)?)\s*[:\-]\s*(.+)$", ln, re.I)
            if m:
                L["exceptions"].append({"control_id": m.group(1).upper(), "description": m.group(2).strip(), "page": pn, "quote": _quote(ln)})
    L["cuecs"] = []
    for pn, page in enumerate(pages, 1):
        for ln in page.split("\n"):
            m = re.search(r"CUEC[- ]?\d*\s*[:\-]\s*(.+)$", ln, re.I)
            if m:
                L["cuecs"].append({"text": m.group(1).strip(), "page": pn, "quote": _quote(ln)})
    return {"fields": F, "lists": L}


# ---------------------------------------------------------------------------- other documents
def extract_iso(pages):
    F = []
    h = _hit(pages, re.compile(r"ISO/?\s?IEC\s*27001(?::\s?\d{4})?", re.I))
    F.append(_field("standard", h[2].group(0) if h else None, h))
    h = _hit(pages, re.compile(r"certification\s+body\s*[:\-]\s*(.+)$", re.I))
    F.append(_field("certification_body", h[2].group(1).strip() if h else None, h))
    h = _hit(pages, re.compile(r"scope\s*[:\-]\s*(.+)$", re.I))
    F.append(_field("scope_statement", h[2].group(1).strip() if h else None, h))
    h = _hit(pages, re.compile(r"(?:valid\s+until|expiry\s+date|expiration\s+date)\s*[:\-]?\s*.+", re.I))
    F.append(_field("valid_until", _date_in(h[1]) if h else None, h))
    h = _hit(pages, re.compile(r"status\s*[:\-]\s*(\w+)", re.I))
    F.append(_field("status", h[2].group(1).lower() if h else None, h))
    return {"fields": F, "lists": {}}


def extract_insurance(pages):
    F = []
    h = _hit(pages, re.compile(r"named\s+insured\s*[:\-]\s*(.+)$", re.I))
    F.append(_field("named_insured", h[2].group(1).strip() if h else None, h))
    h = _hit(pages, re.compile(r"cyber[^\n]*(?:limit|coverage)[^\n]*", re.I))
    F.append(_field("cyber_limit_usd", _money(h[1].split(":", 1)[-1]) if h else None, h))
    h = _hit(pages, re.compile(r"(?:expiry\s+date|expiration\s+date|valid\s+until|policy\s+period\s+end)\s*[:\-]?\s*.+", re.I))
    F.append(_field("valid_until", _date_in(h[1]) if h else None, h))
    return {"fields": F, "lists": {}}


def extract_pentest(pages):
    F = []
    h = _hit(pages, re.compile(r"(?:test\s+date|date\s+of\s+(?:the\s+)?test|testing\s+performed)\s*[:\-]?\s*.+", re.I))
    F.append(_field("test_date", _date_in(h[1]) if h else None, h))
    h = _hit(pages, re.compile(r"critical\s+findings?\s*[:\-]?\s*(\d+)\s*(?:\(?\s*(\d+)\s*unresolved)?", re.I))
    if h:
        unresolved = int(h[2].group(2)) if h[2].group(2) is not None else int(h[2].group(1))
        F.append(_field("unresolved_critical", unresolved, h))
    else:
        F.append(_field("unresolved_critical"))
    h = _hit(pages, re.compile(r"scope\s*[:\-]\s*(.+)$", re.I))
    if h:
        txt = h[2].group(1).lower()
        prod = "production" in txt and not re.search(r"(excl\w*|not\s+includ\w*)\s+production|production\s+(?:is\s+)?(?:excluded|out of scope)", txt)
        F.append(_field("scope_includes_production", bool(prod), h))
    else:
        F.append(_field("scope_includes_production"))
    return {"fields": F, "lists": {}}


def extract_bcp(pages):
    F = []
    for key, rx in (("rto_hours", r"RTO[^\n\d]{0,40}(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b"), ("rpo_hours", r"RPO[^\n\d]{0,40}(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b")):
        h = _hit(pages, re.compile(rx, re.I))
        F.append(_field(key, float(h[2].group(1)) if h else None, h))
    h = _hit(pages, re.compile(r"(?:last\s+(?:dr|disaster\s+recovery)\s+test|dr\s+test\s+date)[^\n]*", re.I))
    if h and re.search(r"never|not\s+(?:yet\s+)?tested|no\s+test", h[1], re.I):
        F.append(_field("dr_last_tested", "never", h))
    else:
        F.append(_field("dr_last_tested", _date_in(h[1]) if h else None, h))
    h = _hit(pages, re.compile(r"(?:regions?|data\s*cent(?:er|re)s?)\s*(?:in\s+operation)?\s*[:\-]\s*(.+)$", re.I))
    F.append(_field("regions", _split_list(h[2].group(1)) if h else None, h))
    return {"fields": F, "lists": {}}


CLAUSES = {   # clause_key -> regex that evidences the clause is PRESENT in a contract
    "audit_rights": re.compile(r"(right\s+to\s+audit|audit\s+rights?|inspect(?:ion)?\s+rights?|audit\s+and\s+inspect)", re.I),
    "subcontractor_flowdown": re.compile(r"(sub-?contractors?|sub-?processors?)[^.\n]{0,80}(flow[- ]?down|same\s+(?:obligations|terms)|bound\s+by)", re.I),
    "exit_assistance": re.compile(r"(exit\s+(?:assistance|plan|support)|transition\s+assistance|termination\s+assistance)", re.I),
    "breach_notification": re.compile(r"(notify|notification)[^.\n]{0,80}within\s+\d+\s+hours", re.I),
    "data_location": re.compile(r"(data\s+(?:location|residency)|(?:stored|processed|hosted)\s+(?:only\s+)?in)", re.I),
    "regulator_inspection_access": re.compile(r"regulators?[^.\n]{0,80}(access|inspect|audit)", re.I),
    "dora_termination_rights": re.compile(r"(terminat\w+)[^.\n]{0,100}(regulator|supervis|ict\s+risk)", re.I),
}


def extract_contract(pages):
    F, L = [], {"clauses": []}
    full = "\n".join(pages)
    for key, rx in CLAUSES.items():
        h = _hit(pages, rx)
        L["clauses"].append({"clause": key, "present": bool(h), "page": h[0] if h else 1,
                             "quote": _quote(h[1]) if h else _quote(pages[0].strip().split("\n")[0]), "locator": f"absence:{key}" if not h else key})
    h = _hit(pages, re.compile(r"within\s+(\d+)\s+hours", re.I))
    F.append(_field("breach_notice_hours", int(h[2].group(1)) if h else None, h))
    h = _hit(pages, re.compile(r"liability[^\n]{0,120}?(?:cap(?:ped)?|limit(?:ed)?)[^\n]{0,80}", re.I))
    mult = None
    if h:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|times)\s*(?:the\s+)?(?:annual|fees|contract)", h[1], re.I)
        mult = float(m.group(1)) if m else None
    F.append(_field("liability_cap_multiple", mult, h))
    h = _hit(pages, re.compile(r"(?:data\s+(?:location|residency)|stored\s+and\s+processed\s+(?:only\s+)?in)[^\n]*", re.I))
    F.append(_field("data_location_text", h[1] if h else None, h))
    return {"fields": F, "lists": L}


def extract_dpa(pages):
    F = []
    h = _hit(pages, re.compile(r"sub-?processors?\s*(?:list)?\s*:[^\n]*", re.I))
    F.append(_field("subprocessors_listed", bool(re.search(r":\s*\S+", h[1])), h) if h else _field("subprocessors_listed"))
    h = _hit(pages, re.compile(r"(standard\s+contractual\s+clauses|SCCs?|adequacy\s+decision|binding\s+corporate\s+rules|BCRs?)", re.I))
    if h:
        F.append(_field("transfer_mechanism", h[2].group(1), h))
    else:   # absence of any mechanism: anchored to the document's first line so the evidence still resolves
        F.append({"name": "transfer_mechanism", "value": "none", "found": True, "page": 1, "quote": _quote(pages[0].strip().split("\n")[0])})
    return {"fields": F, "lists": {}}


def extract_financial(pages):
    F = []
    h = _hit(pages, re.compile(r"going\s+concern", re.I))
    def _doubt(line: str) -> bool:
        pos = re.search(r"(substantial\s+doubt|material\s+uncertaint)", line, re.I)
        neg = re.search(r"\b(no|not|without|absence)\b[^.]{0,60}(substantial\s+doubt|material\s+uncertaint)", line, re.I)
        return bool(pos and not neg)
    F.append(_field("going_concern_doubt", _doubt(h[1]), h) if h else _field("going_concern_doubt"))
    h = _hit(pages, re.compile(r"total\s+(?:shareholders'?\s+)?equity[^\n]*", re.I))
    F.append(_field("total_equity_usd", _money(h[1].split(":", 1)[-1]) if h else None, h))
    ca = _hit(pages, re.compile(r"total\s+current\s+assets[^\n]*", re.I))
    cl = _hit(pages, re.compile(r"total\s+current\s+liabilities[^\n]*", re.I))
    if ca and cl and _money(cl[1].split(":", 1)[-1]):
        ratio = round(_money(ca[1].split(":", 1)[-1]) / abs(_money(cl[1].split(":", 1)[-1])), 3)
        F.append({"name": "current_ratio", "value": ratio, "found": True, "page": ca[0], "quote": _quote(ca[1] + " " + cl[1])})
    else:
        F.append(_field("current_ratio"))
    h = _hit(pages, re.compile(r"(?:largest|top)\s+customer[^\n]*?(\d+(?:\.\d+)?)\s*%", re.I))
    F.append(_field("revenue_concentration_pct", float(h[2].group(1)) if h else None, h))
    return {"fields": F, "lists": {}}


EXTRACTORS = {"soc2_report": extract_soc2, "iso_certificate": extract_iso, "insurance_certificate": extract_insurance,
              "pentest_summary": extract_pentest, "bcp_dr": extract_bcp, "contract": extract_contract, "dpa": extract_dpa,
              "financial_statements": extract_financial}


def reader_extract(req) -> dict:
    ctx = req.context
    fn = EXTRACTORS.get(ctx["doc_type"])
    base = fn(ctx["pages"]) if fn else {"fields": [], "lists": {}}
    return {"doc_id": ctx["doc_id"], "doc_type": ctx["doc_type"], "fields": base["fields"], "lists": base["lists"],
            "flags": ["embedded_instruction_detected"] if ctx.get("had_injection") else []}


# ---------------------------------------------------------------------------- verifier (independent)
SUPPORT_WORDS = {True: re.compile(r"(includ|in[- ]scope|covered|within\s+the\s+(?:system\s+)?boundary|present|provided)", re.I),
                 False: re.compile(r"(exclud|carve|out[- ]of[- ]scope|not\s+includ|absent|no\s+|never|not\s+(?:yet\s+)?tested|without)", re.I)}
ABSOLUTES = re.compile(r"\b(all|every|never|always|fully|entirely|completely|no\s+exceptions|guarantee[sd]?)\b", re.I)
DATEISH = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _num_in(text: str, n: float) -> bool:
    nums = {float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}
    if n in nums:
        return True
    if n >= 1e6 and any(abs(x * 1e6 - n) < 1 for x in nums):    # "$5 million"
        return True
    return any(abs(x - n) < 1e-9 for x in nums)


def _date_in_text(text: str, iso: str) -> bool:
    try:
        d = date.fromisoformat(iso[:10])
    except ValueError:
        return False
    if iso[:10] in text:
        return True
    names = [k for k, v in MONTHS.items() if v == d.month]
    return any(re.search(rf"{n}\s+0?{d.day},?\s+{d.year}", text, re.I) for n in names) or \
        bool(re.search(rf"\b0?{d.day}\s+{names[0]}\s+{d.year}", text, re.I))


def object_supported(predicate: str, obj, quote: str, subject: str | None = None) -> tuple[bool, str]:
    """Does the structured `object` agree with the quoted passage? Used by validators and the verifier."""
    q = quote or ""
    if predicate == "soc2_opinion":
        o = str(obj).lower()
        low = q.lower()
        if o == "unqualified":
            return ("unqualified" in low or ("in our opinion" in low and "qualified" not in low and "adverse" not in low and "express" not in low)), "opinion wording"
        if o == "qualified":
            return ("qualified" in low and "unqualified" not in low) or "except for" in low, "opinion wording"
        return (o in low or ("do not express" in low and o == "disclaimer")), "opinion wording"
    if predicate == "soc2_report_type":
        m = re.search(r"type\s+(ii|2|i|1)\b", q, re.I)
        if not m:
            return False, "report type not in quote"
        return ("Type II" if m.group(1).lower() in ("ii", "2") else "Type I") == str(obj), "report type"
    if isinstance(obj, bool):
        low = q.lower()
        if predicate in ("soc2_service_in_scope", "soc2_service_excluded"):
            return bool(SUPPORT_WORDS[obj].search(q)), "boolean wording"
        if predicate == "pentest_scope_includes_production":
            excl = re.search(r"(excl\w*|not\s+includ\w*)\s+production|production[^.]{0,20}(excluded|out of scope)", low)
            return (("production" in low and not excl) if obj else bool(excl or "production" not in low)), "scope wording"
        if predicate == "financial_going_concern_doubt":
            return bool(re.search(r"substantial doubt|material uncertaint", low)) == obj, "going-concern wording"
        if predicate == "dpa_subprocessors_listed":
            listed = bool(re.search(r"sub-?processors?\s*(?:list)?\s*:\s*\S", q, re.I))
            return listed == obj, "sub-processor list wording"
        if predicate == "contract_clause_present":
            key = (subject or "").split("/")[-1].strip()
            rx = CLAUSES.get(key)
            if not rx:
                return False, f"unknown clause key '{key}'"
            if obj is False:
                return False, "absence must be evidenced by an absence locator, not a quote"
            return bool(rx.search(q)), "clause wording"
        return False, "no verification rule for this boolean predicate"
    if isinstance(obj, (int, float)):
        if predicate == "financial_current_ratio":
            ca = re.search(r"total\s+current\s+assets[^\d$(-]*([\d,().$-]+)", q, re.I)
            cl = re.search(r"total\s+current\s+liabilities[^\d$(-]*([\d,().$-]+)", q, re.I)
            a_, l_ = (_money(ca.group(1)) if ca else None), (_money(cl.group(1)) if cl else None)
            if a_ is None or not l_:
                return False, "quote must contain both current assets and current liabilities"
            return abs(a_ / abs(l_) - float(obj)) < 0.01, "ratio recomputed from quoted figures"
        return _num_in(q, float(obj)), "number in quote"
    if isinstance(obj, str) and DATEISH.match(obj):
        return _date_in_text(q, obj), "date in quote"
    if isinstance(obj, str) and obj and obj != "none":
        return norm(obj) in norm(q), "text in quote"
    return True, "no object check"


def verifier_verify(req) -> dict:
    """Input context: {"items": [{claim_id, statement, predicate, object, evidence: [{quote, passage_pages|passage, locator, doc_text_for_absence}]}]}.
    The verifier never sees the author's rationale (A10 independence)."""
    out = []
    for it in req.context["items"]:
        verdict, defect, minimal = "UNSUPPORTED", "no supporting passage found", None
        stance_contra = False
        for ev in it["evidence"]:
            loc = ev.get("locator") or ""
            if loc.startswith("absence:"):
                key = loc.split(":", 1)[1]
                rx = CLAUSES.get(key)
                present = bool(rx and rx.search(ev.get("doc_text") or ""))
                if it["object"] is False and not present:
                    verdict, defect, minimal = "SUPPORTED", None, f"no text matching '{key}' found anywhere in the document"
                elif it["object"] is True and present:
                    verdict, defect, minimal = "SUPPORTED", None, f"clause '{key}' text found in the document"
                else:
                    verdict, defect = "CONTRADICTED", f"document {'contains' if present else 'does not contain'} text for '{key}'"
                break
            if ev.get("source_kind") != "document":
                # non-document evidence (policy table / list / human): verifier can only confirm the evidence record exists
                verdict, defect, minimal = "SUPPORTED", None, f"evidence record {loc or ev.get('source_kind')} present (non-document source)"
                break
            quote = ev.get("quote") or ""
            score, page = locate_quote(ev.get("pages") or [], quote)
            if page is None:
                verdict, defect = "UNSUPPORTED", f"quote not found in cited document (best match {score})"
                continue
            ok, why = object_supported(it["predicate"], it["object"], quote, it.get("subject"))
            if not ok:
                verdict, defect, minimal = "CONTRADICTED", f"quoted passage does not support the claimed value ({why})", quote
                continue
            if ABSOLUTES.search(it["statement"]) and not ABSOLUTES.search(quote):
                verdict, defect, minimal = "OVERSTATED", "statement uses absolute wording not present in the evidence", quote
                continue
            verdict, defect, minimal = "SUPPORTED", None, quote
            break
        out.append({"claim_id": it["claim_id"], "verdict": verdict, "minimal_quote": minimal, "defect": defect})
    return {"verdicts": out}


# ---------------------------------------------------------------------------- narrative & comms
def synth_narrative(req) -> dict:
    c = req.context
    top = c["top_findings"]
    lines = [f"Evidence suggests residual risk is {c['band']} (score {c['residual_score']}) against an inherent score of "
             f"{c['inherent_score']} (tier T{c['tier']}). This requires human review."]
    if top:
        lines.append("Principal issues for the reviewer: " + "; ".join(f"{f['title']} [{f['severity']}]" for f in top[:5]) + ".")
    else:
        lines.append("No material findings were raised from the verified evidence.")
    if c.get("unverified"):
        lines.append(f"{c['unverified']} claim(s) are not yet verified and are excluded from scoring.")
    if c.get("missing_docs"):
        lines.append("Evidence not provided: " + ", ".join(c["missing_docs"]) + ". Missing evidence is scored as zero coverage, never assumed acceptable.")
    return {"narrative": " ".join(lines)}


def comms_draft(req) -> dict:
    c = req.context
    kind = c["kind"]
    if kind == "document_request":
        items = "\n".join(f"  - {d.replace('_', ' ')}" for d in c["missing_docs"])
        body = (f"DRAFT - NOT SENT. Requires analyst review before sending.\n\nSubject: Information request for onboarding of {c['vendor']}\n\n"
                f"Dear {c.get('contact', 'vendor contact')},\n\nTo complete our third-party due diligence, please provide current copies of:\n{items}\n\n"
                f"Documents should be dated within the last 12 months where applicable.\n\nKind regards,\n{c.get('owner', 'Third-Party Risk Management')}")
    elif kind == "remediation_request":
        items = "\n".join(f"  - [{f['severity']}] {f['title']}: {f.get('remediation') or 'please provide a remediation plan'}" for f in c["findings"])
        body = f"DRAFT - NOT SENT.\n\nSubject: Remediation items for {c['vendor']}\n\nOur review identified the following items:\n{items}\n\nPlease respond with a plan and target dates."
    else:
        body = f"DRAFT - NOT SENT.\n\n{c.get('summary', '')}"
    return {"body": body, "kind": kind}


TASKS = {"reader.extract": reader_extract, "verifier.verify": verifier_verify, "synth.narrative": synth_narrative,
         "comms.draft": comms_draft, "specialist.review": lambda req: {"extra_findings": []}}
