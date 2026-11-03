"""Deterministic specialist rules for A5 (security/resilience), A6 (financial), A7 (privacy/regulatory/contract),
A8 (concentration). R1: LLMs propose, deterministic code disposes - severities follow the plan's rubric (§15.2) and
control-effectiveness inputs feed the scoring engine. Missing required evidence is scored as ZERO coverage.

Each rule cites claim ids. Absence/inventory facts are anchored by deterministic "gap claims" (api evidence) created via
`facts.gap_claim`, so every finding still satisfies R2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from ..models import Finding
from ..screening import jaro_winkler, normalise, token_set_ratio
from ..scoring import CheckResult
from ..util import parse_date

EU27 = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL",
        "PT", "RO", "SK", "SI", "ES", "SE"}
REGION_COUNTRIES = {"EU": EU27 | {"NO", "IS", "LI"}, "US": {"US"}, "IN": {"IN"}, "UK": {"GB"}}
PII_CLASSES = {"customer_pii", "payment_card", "authentication_secrets"}


@dataclass
class Facts:
    claims: list[dict]                       # claims with 'evidence' already attached
    docs: list[dict]
    intake: dict
    plan: dict
    policy: object
    today: date
    tier: int
    gap_claim: Callable[[str, str, str, object], str]    # (predicate, subject, statement, object) -> claim_id
    portfolio: list[dict] = field(default_factory=list)  # other onboarded vendors' intakes (for concentration)

    def all(self, predicate: str) -> list[dict]:
        return [c for c in self.claims if c["predicate"] == predicate]

    def first(self, predicate: str) -> dict | None:
        a = self.all(predicate)
        return a[0] if a else None

    def val(self, predicate: str):
        c = self.first(predicate)
        return c["object"] if c else None

    def doc(self, doc_type: str) -> dict | None:
        ds = [d for d in self.docs if d["doc_type"] == doc_type]
        return ds[-1] if ds else None

    def required(self, doc_type: str) -> bool:
        return doc_type in self.plan["required_docs"]

    @property
    def data_types(self) -> set:
        return set(self.intake["data_access"]["data_types"])

    @property
    def handles_pii(self) -> bool:
        return bool(self.data_types & PII_CLASSES)


@dataclass
class Out:
    checks: dict[str, list[CheckResult]] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)

    def chk(self, domain, cid, w, cov, q, note=""):
        self.checks.setdefault(domain, []).append(CheckResult(cid, w, max(0.0, min(1.0, cov)), max(0.0, min(1.0, q)), note))

    def fnd(self, domain, sev, title, desc, claim_ids, rule_id, refs=None, remediation=None):
        self.findings.append(Finding(domain=domain, severity=sev, title=title, description=desc, claim_ids=[c for c in claim_ids if c],
                                     regulation_refs=refs or [], remediation=remediation, rule_id=rule_id))

    def merge(self, o: "Out"):
        for d, cs in o.checks.items():
            self.checks.setdefault(d, []).extend(cs)
        self.findings.extend(o.findings)


def _missing(f: Facts, o: Out, domain: str, doc_type: str, label: str, weight: float, sev: str, rule: str):
    cid = f.gap_claim(f"document_missing:{doc_type}", f.intake["legal_name"], f"No current {label} was provided for this vendor.", True)
    o.chk(domain, f"{doc_type}_present", weight, 0.0, 0.0, "required evidence not provided")
    o.fnd(domain, sev, f"{label} not provided", f"The evidence matrix for tier T{f.tier} requires a {label}; none is on file. "
          "Missing evidence is scored as zero coverage.", [cid], rule, remediation=f"Request a current {label} from the vendor.")


def _age_days(d: date | None, today: date) -> int | None:
    return (today - d).days if d else None


def _sev_by_tier(f: Facts, t1: str, other: str) -> str:
    return t1 if f.tier == 1 else other


# =============================================================================== A5: security & resilience
def security(f: Facts) -> Out:
    o, P, pol = Out(), "security", f.policy.gates
    soc = f.doc("soc2_report")
    refs = f.policy.regulation_ref(f.intake["jurisdictions"], "lifecycle")
    if not soc:
        if f.required("soc2_report"):
            _missing(f, o, P, "soc2_report", "SOC 2 report", 3.0, "HIGH", "SEC-001")
    else:
        o.chk(P, "soc2_present", 3.0, 1.0, 1.0)
        rtype, op = f.first("soc2_report_type"), f.first("soc2_opinion")
        if rtype:
            ok = rtype["object"] == "Type II"
            o.chk(P, "soc2_type", 1.0, 1.0, 1.0 if ok else 0.5)
            if not ok and f.tier <= 2:
                o.fnd(P, _sev_by_tier(f, "HIGH", "MEDIUM"), "SOC 2 Type I provided where Type II is expected",
                      "A Type I report evaluates design at a point in time and does not test operating effectiveness.", [rtype["claim_id"]], "SEC-002", refs,
                      "Request a SOC 2 Type II report covering at least six months.")
        if op:
            o_ = op["object"]
            if o_ == "unqualified":
                o.chk(P, "soc2_opinion", 2.0, 1.0, 1.0)
            else:
                crit = o_ in ("adverse", "disclaimer") or (o_ == "qualified" and f.handles_pii and
                       any(str(e["object"].get("control_id", "")).startswith(("CC6", "CC7")) for e in f.all("soc2_exception") if isinstance(e["object"], dict)))
                o.chk(P, "soc2_opinion", 2.0, 1.0, 0.0 if o_ in ("adverse", "disclaimer") else 0.4)
                o.fnd(P, "CRITICAL" if crit else "HIGH", f"SOC 2 opinion is {o_}",
                      f"The service auditor's opinion is {o_}. Evidence suggests the reviewer should assess the basis for the modification before reliance.",
                      [op["claim_id"]], "SEC-003", refs, "Obtain the basis-for-opinion detail and management's remediation plan.")
        pe = f.first("soc2_period_end")
        if pe:
            age = _age_days(parse_date(str(pe["object"])), f.today)
            limit = pol["soc2_max_age_days"]
            if age is not None and age > limit:
                o.chk(P, "soc2_recency", 2.0, 1.0, 0.1 if age > 540 else 0.4, f"{age} days old")
                o.fnd(P, _sev_by_tier(f, "HIGH", "MEDIUM"), "SOC 2 period ended more than 12 months ago",
                      f"The report period ended {pe['object']} ({age} days ago) and no bridge letter is on file.", [pe["claim_id"]], "SEC-004", refs,
                      "Request a current report or a bridge letter covering the gap.")
            else:
                o.chk(P, "soc2_recency", 2.0, 1.0, 1.0)
        # scope: does an excluded service match what the bank is buying?
        desc_tokens = set(normalise(f.intake["service_description"]).tokens)
        hit = False
        for ex in f.all("soc2_service_excluded"):
            svc = ex["subject"].split(" / ")[-1]
            svc_tokens = [t for t in normalise(svc).tokens if len(t) > 3]
            if svc_tokens and any(jaro_winkler(t, d) >= 0.92 for t in svc_tokens for d in desc_tokens):
                hit = True
                o.fnd(P, "HIGH", f"Required service '{svc}' is outside the SOC 2 scope",
                      f"The SOC 2 report states '{svc}' is excluded, but the intake describes this service as part of what the bank will use. "
                      "No compensating evidence is on file.", [ex["claim_id"]], "SEC-005", refs,
                      "Obtain evidence of controls for the excluded service or restrict use to in-scope services.")
        o.chk(P, "soc2_scope", 3.0, 1.0, 0.0 if hit else 1.0, "required service out of scope" if hit else "")
        excs = [e for e in f.all("soc2_exception")]
        o.chk(P, "soc2_exceptions", 2.0, 1.0, max(0.2, 1.0 - 0.25 * len(excs)))
        for e in excs:
            cid = (e["object"] or {}).get("control_id", "")
            o.fnd(P, "HIGH" if str(cid).startswith(("CC6", "CC7")) else "MEDIUM", f"SOC 2 exception noted for control {cid}",
                  e["statement"], [e["claim_id"]], "SEC-006", refs, "Review management's response and confirm remediation.")
        subs = f.all("soc2_subservice_carved_out")
        o.chk(P, "soc2_subservice", 1.0, 1.0, 0.5 if subs else 1.0)
        for s in subs:
            o.fnd(P, "MEDIUM", f"Carved-out subservice organisation: {s['object']}",
                  f"{s['object']} is carved out of the SOC 2 scope; no evidence of its controls is on file.", [s["claim_id"]], "SEC-007", refs,
                  "Request the subservice organisation's own assurance report.")
        cuecs = f.all("soc2_cuec")
        if cuecs:
            o.fnd(P, "INFO", f"{len(cuecs)} complementary user-entity control(s) the bank must implement",
                  "The report assumes controls at the user entity. Confirm each is implemented.", [cuecs[0]["claim_id"]], "SEC-008", refs)
    iso = f.doc("iso_certificate")
    if not iso:
        if f.required("iso_certificate"):
            _missing(f, o, P, "iso_certificate", "ISO/IEC 27001 certificate", 1.5, "MEDIUM", "SEC-009")
    else:
        vu = f.first("iso27001_valid_until")
        if vu:
            valid = (parse_date(str(vu["object"])) or date.min) >= f.today
            o.chk(P, "iso_valid", 1.5, 1.0, 1.0 if valid else 0.0)
            if not valid:
                o.fnd(P, "MEDIUM", "ISO/IEC 27001 certificate has expired", f"Certificate validity ended {vu['object']}.", [vu["claim_id"]], "SEC-010", refs,
                      "Request the renewed certificate.")
        else:
            o.chk(P, "iso_valid", 1.5, 0.5, 0.5)
    pt = f.doc("pentest_summary")
    if not pt:
        if f.required("pentest_summary"):
            _missing(f, o, P, "pentest_summary", "penetration test summary", 2.0, _sev_by_tier(f, "HIGH", "MEDIUM"), "SEC-011")
    else:
        unresolved = f.first("pentest_unresolved_critical")
        q = 1.0
        if unresolved and unresolved["object"] and unresolved["object"] > 0:
            q = 0.0
            o.fnd(P, "CRITICAL", f"Penetration test reports {int(unresolved['object'])} unresolved critical finding(s)",
                  unresolved["statement"], [unresolved["claim_id"]], "SEC-012", refs, "Require remediation evidence and a retest before onboarding.")
        td = f.first("pentest_date")
        if td:
            age = _age_days(parse_date(str(td["object"])), f.today)
            if age is not None and age > pol["pentest_max_age_days"]:
                q = min(q, 0.5)
                o.fnd(P, "MEDIUM", "Penetration test is more than 12 months old", f"Test date {td['object']} ({age} days ago).", [td["claim_id"]], "SEC-013", refs,
                      "Request a current penetration test.")
        sc = f.first("pentest_scope_includes_production")
        if sc and sc["object"] is False:
            q = min(q, 0.6)
            o.fnd(P, "MEDIUM", "Penetration test scope excludes production", sc["statement"], [sc["claim_id"]], "SEC-014", refs,
                  "Request testing that covers production-equivalent systems.")
        o.chk(P, "pentest", 2.0, 1.0, q)
    return o


def resilience(f: Facts) -> Out:
    o, P, pol = Out(), "resilience", f.policy.gates
    b = f.doc("bcp_dr")
    if not b:
        if f.required("bcp_dr"):
            _missing(f, o, P, "bcp_dr", "business continuity / disaster recovery plan", 2.0, "MEDIUM", "RES-001")
        return o
    o.chk(P, "bcp_present", 2.0, 1.0, 1.0)
    rto = f.first("bcp_rto_hours")
    if rto and f.tier == 1:
        req = pol["bank_rto_hours_tier1"]
        ok = rto["object"] <= req
        o.chk(P, "rto", 2.0, 1.0, 1.0 if ok else min(1.0, req / max(rto["object"], 0.1)))
        if not ok:
            o.fnd(P, "HIGH", f"Vendor RTO ({rto['object']:g}h) exceeds the bank's tier-1 requirement ({req}h)", rto["statement"], [rto["claim_id"]], "RES-002",
                  remediation="Negotiate a lower RTO or document compensating controls.")
    dr = f.first("bcp_dr_last_tested")
    if dr:
        if dr["object"] == "never":
            o.chk(P, "dr_tested", 2.0, 1.0, 0.0)
            o.fnd(P, "HIGH", "Disaster recovery has never been tested", dr["statement"], [dr["claim_id"]], "RES-003", remediation="Require a DR test with results.")
        else:
            age = _age_days(parse_date(str(dr["object"])), f.today)
            stale = age is not None and age > 365
            o.chk(P, "dr_tested", 2.0, 1.0, 0.5 if stale else 1.0)
            if stale:
                o.fnd(P, "MEDIUM", "Last DR test is more than 12 months old", dr["statement"], [dr["claim_id"]], "RES-004")
    rg = f.first("bcp_regions")
    if rg and isinstance(rg["object"], list):
        single = len(rg["object"]) < 2
        o.chk(P, "regions", 1.0, 1.0, 0.4 if single else 1.0)
        if single and f.tier <= 2:
            o.fnd(P, "MEDIUM", "Service runs in a single region", rg["statement"], [rg["claim_id"]], "RES-005", remediation="Ask about multi-region recovery.")
    return o


# =============================================================================== A6: financial & entity health
def financial(f: Facts) -> Out:
    o, P = Out(), "financial"
    fs = f.doc("financial_statements")
    if not fs:
        if f.required("financial_statements"):
            _missing(f, o, P, "financial_statements", "financial statements", 2.0, "MEDIUM", "FIN-001")
    else:
        o.chk(P, "financials_present", 2.0, 1.0, 1.0)
        q = 1.0
        gc = f.first("financial_going_concern_doubt")
        if gc and gc["object"] is True:
            q = 0.0
            o.fnd(P, "HIGH", "Going-concern doubt disclosed", gc["statement"], [gc["claim_id"]], "FIN-002", remediation="Assess viability and exit options.")
        eq = f.first("financial_total_equity_usd")
        if eq and isinstance(eq["object"], (int, float)) and eq["object"] < 0:
            q = min(q, 0.3)
            o.fnd(P, "HIGH", "Negative shareholders' equity", eq["statement"], [eq["claim_id"]], "FIN-003")
        cr = f.first("financial_current_ratio")
        if cr and cr["object"] < 1.0:
            q = min(q, 0.6)
            o.fnd(P, "MEDIUM", f"Current ratio below 1.0 ({cr['object']})", cr["statement"], [cr["claim_id"]], "FIN-004")
        rc = f.first("financial_revenue_concentration_pct")
        if rc and rc["object"] > 60:
            q = min(q, 0.7)
            o.fnd(P, "MEDIUM", f"Revenue concentration above 60% ({rc['object']:g}%)", rc["statement"], [rc["claim_id"]], "FIN-005")
        o.chk(P, "financial_health", 2.0, 1.0, q)
    ins = f.doc("insurance_certificate")
    if not ins:
        if f.required("insurance_certificate"):
            _missing(f, o, P, "insurance_certificate", "certificate of insurance", 2.0, "MEDIUM", "FIN-006")
    else:
        q = 1.0
        lim = f.first("insurance_cyber_limit_usd")
        minimum = f.policy.gates["min_cyber_insurance_usd"]
        if lim and lim["object"] < minimum:
            q = 0.5
            o.fnd(P, "MEDIUM", "Cyber insurance below the policy minimum", f"{lim['statement']} Policy minimum is ${minimum:,.0f}.", [lim["claim_id"]], "FIN-007",
                  remediation="Require increased cover or an accepted exception.")
        vu = f.first("insurance_valid_until")
        if vu and (parse_date(str(vu["object"])) or date.min) < f.today:
            q = 0.0
            o.fnd(P, "MEDIUM", "Insurance policy has expired", vu["statement"], [vu["claim_id"]], "FIN-008", remediation="Request the renewed certificate.")
        ni = f.first("insurance_named_insured")
        if ni and token_set_ratio(normalise(str(ni["object"])).tokens, normalise(f.intake["legal_name"]).tokens) < 0.8:
            q = min(q, 0.4)
            o.fnd(P, "MEDIUM", "Named insured does not match the vendor's legal name", ni["statement"], [ni["claim_id"]], "FIN-009")
        o.chk(P, "insurance", 2.0, 1.0, q)
    return o


# =============================================================================== A7: privacy, regulatory & contract
def _cross_border(f: Facts) -> bool:
    allowed = set()
    for j in f.intake["jurisdictions"]:
        allowed |= REGION_COUNTRIES.get(j, set())
    locs = [x.strip().upper()[:2] for x in f.intake["data_access"].get("storage_locations", []) if x.strip()]
    return bool(allowed and any(l not in allowed for l in locs))


def privacy_contract(f: Facts) -> Out:
    o, pol = Out(), f.policy.gates
    reg_priv = f.policy.regulation_ref(f.intake["jurisdictions"], "privacy")
    reg_life = f.policy.regulation_ref(f.intake["jurisdictions"], "lifecycle")
    dpa = f.doc("dpa")
    need_dpa = f.required("dpa") or f.handles_pii
    if not dpa:
        if need_dpa:
            _missing(f, o, "privacy", "dpa", "data processing agreement", 3.0, "HIGH" if f.handles_pii else "MEDIUM", "PRV-001")
    else:
        o.chk("privacy", "dpa_present", 3.0, 1.0, 1.0)
        sp = f.first("dpa_subprocessors_listed")
        if sp:
            o.chk("privacy", "subprocessors_listed", 2.0, 1.0, 1.0 if sp["object"] else 0.0)
            if not sp["object"]:
                o.fnd("privacy", "MEDIUM", "Sub-processors are not disclosed", sp["statement"], [sp["claim_id"]], "PRV-002", reg_priv,
                      "Request a complete sub-processor list with locations.")
        tm = f.first("dpa_transfer_mechanism")
        xb = _cross_border(f)
        if tm:
            bad = xb and tm["object"] == "none"
            o.chk("privacy", "transfer_mechanism", 2.0, 1.0, 0.0 if bad else 1.0)
            if bad:
                o.fnd("privacy", "HIGH", "Cross-border transfer without a transfer mechanism",
                      "Data is stored outside the bank's jurisdictions and the DPA names no transfer mechanism.", [tm["claim_id"]], "PRV-003", reg_priv,
                      "Require SCCs/BCRs or an adequacy basis before onboarding.")
    if "IN" in f.intake["jurisdictions"] and f.policy.regions.get("IN", {}).get("data_localisation_check"):
        locs = [x.strip().upper()[:2] for x in f.intake["data_access"].get("storage_locations", []) if x.strip()]
        if locs and any(l != "IN" for l in locs) and f.handles_pii:
            cid = f.gap_claim("regulatory_data_location", f.intake["legal_name"], f"Declared storage locations include {locs}, outside India.", locs)
            o.fnd("regulatory", "MEDIUM", "Data location may conflict with localisation expectations (VERIFY with Compliance)",
                  "Intake declares storage outside India for personal data.", [cid], "REG-001", f.policy.regulation_ref(["IN"], "privacy"))
    ct = f.doc("contract")
    if not ct:
        if f.required("contract"):
            _missing(f, o, "contract", "contract", "services contract", 2.0, _sev_by_tier(f, "HIGH", "MEDIUM"), "CON-001")
        return o
    o.chk("contract", "contract_present", 2.0, 1.0, 1.0)
    SEV = {"audit_rights": "HIGH", "regulator_inspection_access": "HIGH", "dora_termination_rights": "HIGH"}
    for key in f.plan["required_clauses"]:
        cl = [x for x in f.all("contract_clause_present") if x["subject"].endswith("/ " + key)]
        if not cl:
            continue
        present = cl[0]["object"] is True
        o.chk("contract", f"clause_{key}", 1.0, 1.0, 1.0 if present else 0.0)
        if not present:
            o.fnd("contract", SEV.get(key, "MEDIUM"), f"Contract lacks a required clause: {key.replace('_', ' ')}",
                  cl[0]["statement"], [cl[0]["claim_id"]], f"CON-{key}", reg_life, f"Negotiate a {key.replace('_', ' ')} clause.")
    bn = f.first("contract_breach_notice_hours")
    if bn:
        ok = bn["object"] <= pol["max_breach_notice_hours"]
        o.chk("contract", "breach_notice", 1.0, 1.0, 1.0 if ok else 0.5)
        if not ok:
            o.fnd("contract", "MEDIUM", f"Breach notice window is {int(bn['object'])}h (policy maximum {pol['max_breach_notice_hours']}h)", bn["statement"],
                  [bn["claim_id"]], "CON-breach-hours", reg_life, "Negotiate a shorter breach-notification period.")
    lc = f.first("contract_liability_cap_multiple")
    if lc and lc["object"] is not None and lc["object"] < pol["min_liability_cap_multiple"]:
        o.fnd("contract", "MEDIUM", "Liability cap below the policy minimum", lc["statement"], [lc["claim_id"]], "CON-liability", remediation="Negotiate a higher cap.")
    return o


# =============================================================================== A8: concentration & fourth parties
def concentration(f: Facts) -> Out:
    o = Out()
    subs = [s for s in f.intake.get("subcontractors", []) if s.strip()]
    for s in subs:
        key = normalise(s).joined
        peers = [p for p in f.portfolio if any(normalise(x).joined == key for x in p.get("subcontractors", []))]
        if len(peers) >= 3:
            cid = f.gap_claim("concentration_shared_fourth_party", s, f"{len(peers) + 1} onboarded vendors (including this one) depend on {s}.", len(peers) + 1)
            o.fnd("concentration", "MEDIUM", f"Concentration: {len(peers) + 1} vendors depend on fourth party '{s}'",
                  "Shared dependency on one fourth party increases systemic risk.", [cid], "CNC-001", remediation="Assess substitutability and exit options for the shared dependency.")
    owners = f.intake.get("declared_owners", [])
    if not owners:
        cid = f.gap_claim("ownership_undisclosed", f.intake["legal_name"], "No beneficial ownership information was declared.", True)
        o.fnd("entity", "HIGH" if f.tier <= 2 else "MEDIUM", "Beneficial ownership is unresolved",
              "No declared owners were provided, so the ultimate beneficial owner cannot be screened.", [cid], "ENT-001",
              remediation="Obtain an ownership declaration (>=25% holders).")
    return o


def document_integrity(f: Facts) -> Out:
    o = Out()
    for d in f.docs:
        flags = d.get("injection_flags") or []
        if flags:
            kinds = sorted({x["kind"] for x in flags})
            cid = f.gap_claim("document_integrity_flag", f"{f.intake['legal_name']} / {d['filename']}",
                              f"Document {d['filename']} contains hidden or instruction-like content ({', '.join(kinds)}).", kinds)
            o.fnd("document_integrity", "HIGH", f"Vendor document '{d['filename']}' contains embedded instructions or hidden text",
                  "Content addressed to automated reviewers was detected and neutralised before analysis. Treat the document and the submission "
                  "as a manipulation signal and review manually.", [cid], "DOC-001", remediation="Escalate to security; ask the vendor to resubmit a clean copy.")
        if d.get("ocr_quality") == "low":
            cid = f.gap_claim("document_low_ocr_quality", f"{f.intake['legal_name']} / {d['filename']}",
                              f"Document {d['filename']} was read from a scan with low OCR confidence.", True)
            o.fnd("document_integrity", "MEDIUM", f"Scanned document '{d['filename']}' was machine-read with low confidence",
                  "Numbers, dates and names extracted from this scan may be misread. Every value taken from it needs human confirmation against the original.",
                  [cid], "DOC-002", remediation="Ask the vendor for a text-based PDF or DOCX, or have an analyst confirm the extracted values.")
    return o


SPECIALISTS = {"A5": [security, resilience], "A6": [financial], "A7": [privacy_contract], "A8": [concentration, document_integrity]}
