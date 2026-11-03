"""Approval packet (plan §13): the document a human approver reads. Every statement links to its evidence (R2).
Only TRUSTED claims support findings; everything else sits in a clearly labelled 'unverified' appendix. Jinja2 autoescape is ON:
all vendor-derived text is escaped."""
from __future__ import annotations

from jinja2 import Environment, select_autoescape

from .agents.services import Services

SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


def build(svc: Services, case_id: str) -> dict:
    case = svc.case(case_id)
    st = svc.store
    vendor = st.get("vendor", "vendor_id", case["vendor_id"]) or {}
    a = st.one("SELECT * FROM assessments WHERE case_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (case_id,))
    claims = {c["claim_id"]: c for c in svc.ledger.get_claims(case["tenant_id"], case["vendor_id"], include_stale=True, with_evidence=True)}
    for c in st.query("SELECT * FROM claims WHERE vendor_id=? AND status IN ('REFUTED','SUPERSEDED')", (case["vendor_id"],)):
        claims.setdefault(c["claim_id"], {**c, "evidence": svc.ledger.evidence(c["claim_id"]), "badge": c["status"]})
    docs = {d["doc_id"]: d for d in st.query("SELECT doc_id, doc_type, filename, sha256, uploaded_at FROM documents WHERE vendor_id=?", (case["vendor_id"],))}

    def cite(cid):
        c = claims.get(cid)
        if not c:
            return None
        ev = [{"doc_id": e["doc_id"], "filename": (docs.get(e["doc_id"]) or {}).get("filename"), "page": e["page"], "quote": e["quote"],
               "locator": e["locator"], "source_type": e["source_type"], "sha256": (e["source_sha256"] or "")[:12]} for e in c.get("evidence", [])]
        return {"claim_id": cid, "statement": c["statement"], "status": c["status"], "badge": c.get("badge", c["status"]), "evidence": ev}

    findings = []
    for f in st.query("SELECT * FROM findings WHERE case_id=? AND status='OPEN'", (case_id,)):
        f["citations"] = [x for x in (cite(c) for c in (f["claim_ids"] or [])) if x]
        findings.append(f)
    findings.sort(key=lambda f: SEV_ORDER.get(f["severity"], 9))
    unverified = [cite(c["claim_id"]) for c in claims.values() if c["status"] != "TRUSTED"]
    screening = st.query("SELECT subject_name, subject_role, match_name, score, auto_disposition, recommendation, human_disposition, dispositioned_by, rationale, list_version "
                         "FROM screening_results WHERE case_id=? ORDER BY score DESC", (case_id,))
    approvals = st.query("SELECT gate, approver_id, decision, rationale, conditions, decided_at FROM approvals WHERE case_id=? ORDER BY decided_at", (case_id,))
    plan = svc.case_plan(case_id)
    have = {d["doc_type"] for d in docs.values()}
    chain = st.verify_audit_chain()
    return {
        "case": {k: case[k] for k in ("case_id", "state", "proposed_tier", "final_tier", "requester_id", "preparer_id", "conditional_expires", "created_at")},
        "vendor": {"name": case["intake"]["legal_name"], "country": case["intake"]["country_iso2"], "service": case["intake"]["service_description"],
                   "owner": case["intake"]["business_owner"], "spend": case["intake"].get("annual_spend_usd")},
        "assessment": None if not a else {"scoring_version": a["scoring_version"], "inherent": a["inherent"], "residual": a["residual"],
                                          "ce": {d: v["ce"] for d, v in (a["control_effectiveness"] or {}).items()}, "narrative": a["narrative"], "created_at": a["created_at"]},
        "findings": findings, "unverified": [u for u in unverified if u], "screening": screening, "approvals": approvals,
        "required_docs": [{"doc_type": d, "present": d in have} for d in plan["required_docs"]],
        "policy_version": svc.policy.version, "regulation_refs": plan["regulation_refs"],
        "open_critical": sum(1 for f in findings if f["severity"] == "CRITICAL" and f["disposition"] not in ("REMEDIATED", "ACCEPT_RISK")),
        "audit_chain": chain, "disclaimer": "Decision support only. Regulatory references are engineering inputs marked VERIFY and are not legal advice.",
    }


_env = Environment(autoescape=select_autoescape(default=True, default_for_string=True))
TEMPLATE = _env.from_string("""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Approval packet - {{ p.vendor.name }}</title>
<style>body{font:14px/1.5 system-ui,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#1b2430}h1{font-size:22px}h2{font-size:16px;margin-top:28px;border-bottom:1px solid #d5dbe3;padding-bottom:4px}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #d5dbe3;padding:6px 8px;text-align:left;vertical-align:top}th{background:#f3f5f8}
.sev{font-weight:600;padding:1px 6px;border-radius:4px;color:#fff}.CRITICAL{background:#8b1a1a}.HIGH{background:#c2410c}.MEDIUM{background:#a16207}.LOW{background:#4d7c0f}.INFO{background:#64748b}
.q{color:#475569;font-style:italic}.warn{background:#fff7ed;border:1px solid #fdba74;padding:8px;border-radius:6px}.small{font-size:12px;color:#64748b}</style></head><body>
<h1>Approval packet: {{ p.vendor.name }}</h1>
<p class="small">SYNTHETIC / DECISION SUPPORT - {{ p.disclaimer }} Case {{ p.case.case_id }} &middot; state {{ p.case.state }} &middot; tier T{{ p.case.final_tier or p.case.proposed_tier }} &middot; policy {{ p.policy_version }}</p>
<h2>Summary</h2>
{% if p.assessment %}<p>{{ p.assessment.narrative }}</p>
<table><tr><th>Inherent score</th><th>Weighted control effectiveness</th><th>Residual score</th><th>Residual band</th><th>Scoring version</th></tr>
<tr><td>{{ p.assessment.inherent.inherent_score }}</td><td>{{ p.assessment.residual.weighted_control_effectiveness }}</td><td>{{ p.assessment.residual.residual_score }}</td><td>{{ p.assessment.residual.band }}{% if p.assessment.residual.critical_cap_applied %} (floor applied){% endif %}</td><td>{{ p.assessment.scoring_version }}</td></tr></table>
{% else %}<p class="warn">No assessment has been produced yet.</p>{% endif %}
{% if p.open_critical %}<p class="warn"><b>{{ p.open_critical }} CRITICAL finding(s) are open.</b> Approval is blocked until each is remediated or has a time-boxed exception.</p>{% endif %}
<h2>Sanctions and ownership screening</h2>
<table><tr><th>Subject</th><th>Role</th><th>Best list candidate</th><th>Score</th><th>System</th><th>Human disposition (G1)</th></tr>
{% for s in p.screening %}<tr><td>{{ s.subject_name }}</td><td>{{ s.subject_role }}</td><td>{{ s.match_name or '-' }}</td><td>{{ '%.2f'|format(s.score) }}</td><td>{{ s.auto_disposition }} / {{ s.recommendation }}</td><td>{{ s.human_disposition or ('-' if s.auto_disposition=='NO_CANDIDATE' else 'PENDING') }}{% if s.dispositioned_by %} by {{ s.dispositioned_by }}{% endif %}{% if s.rationale %}<br><span class="q">{{ s.rationale }}</span>{% endif %}</td></tr>{% endfor %}</table>
<h2>Evidence on file</h2>
<table><tr><th>Required document</th><th>Status</th></tr>{% for d in p.required_docs %}<tr><td>{{ d.doc_type }}</td><td>{{ 'provided' if d.present else 'MISSING (scored as zero coverage)' }}</td></tr>{% endfor %}</table>
<h2>Findings ({{ p.findings|length }})</h2>
{% for f in p.findings %}<div style="margin:12px 0"><span class="sev {{ f.severity }}">{{ f.severity }}</span> <b>{{ f.title }}</b> <span class="small">[{{ f.rule_id }}] {{ f.domain }}</span>
<p>{{ f.description }}</p>
{% if f.remediation %}<p><b>Suggested remediation:</b> {{ f.remediation }}</p>{% endif %}
{% if f.regulation_refs %}<p class="small">References (VERIFY): {{ f.regulation_refs|join('; ') }}</p>{% endif %}
{% if f.disposition %}<p class="small">Disposition: {{ f.disposition }} by {{ f.disposition_by }}{% if f.exception_expires %} until {{ f.exception_expires }}{% endif %}</p>{% endif %}
{% if f.disputed %}<p class="small">Disputed by {{ f.disputed_by }}: {{ f.disputed_reason }}</p>{% endif %}
{% for c in f.citations %}<div class="small">&bull; <b>{{ c.badge }}</b>: {{ c.statement }}{% for e in c.evidence %}<br>&nbsp;&nbsp;{% if e.doc_id %}<a href="/#/doc/{{ p.case.case_id }}/{{ e.doc_id }}?page={{ e.page or 1 }}">{{ e.filename or e.doc_id }} p.{{ e.page or '?' }}</a> &ldquo;{{ e.quote or e.locator }}&rdquo; (sha256 {{ e.sha256 }}){% else %}{{ e.source_type }}: {{ e.locator }}{% endif %}{% endfor %}</div>{% endfor %}
</div>{% else %}<p>No open findings.</p>{% endfor %}
<h2>Control effectiveness by domain</h2>
{% if p.assessment %}<table><tr>{% for d,v in p.assessment.ce.items() %}<th>{{ d }}</th>{% endfor %}</tr><tr>{% for d,v in p.assessment.ce.items() %}<td>{{ v }}</td>{% endfor %}</tr></table>{% endif %}
<h2>Decision history</h2>
<table><tr><th>When</th><th>Gate</th><th>By</th><th>Decision</th><th>Rationale</th></tr>{% for a in p.approvals %}<tr><td>{{ a.decided_at }}</td><td>{{ a.gate }}</td><td>{{ a.approver_id }}</td><td>{{ a.decision }}{% if a.conditions %} ({{ a.conditions|join('; ') }}){% endif %}</td><td>{{ a.rationale }}</td></tr>{% endfor %}</table>
<h2>Appendix: unverified or superseded claims (NOT used in scoring)</h2>
{% for c in p.unverified %}<div class="small">&bull; <b>{{ c.badge }}</b>: {{ c.statement }}</div>{% else %}<p class="small">None.</p>{% endfor %}
<p class="small">Audit chain: {{ 'intact' if p.audit_chain.ok else 'BROKEN at seq ' ~ p.audit_chain.first_bad_seq }} ({{ p.audit_chain.checked }} events). Requester: {{ p.case.requester_id }}; preparer: {{ p.case.preparer_id or '-' }}.</p>
</body></html>""")


def render_html(p: dict) -> str:
    return TEMPLATE.render(p=_Dot(p))


class _Dot(dict):
    """Dict with attribute access so templates read p.vendor.name; nested containers are wrapped lazily."""
    def __getattr__(self, k):
        try:
            return _wrap(self[k])
        except KeyError:
            return None


def _wrap(v):
    if isinstance(v, dict) and not isinstance(v, _Dot):
        return _Dot(v)
    if isinstance(v, list):
        return [_wrap(x) for x in v]
    return v
