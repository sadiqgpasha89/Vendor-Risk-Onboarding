"""Output validation pipeline (plan §6.2): schema -> citation existence -> object/numeric support -> language safety.

Applied to every agent result before anything is persisted. Claims that fail grounding are dropped and reported
(GR-002/GR-003); text is rewritten to avoid legal conclusions (GR-018).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import AgentResult, Claim, Evidence
from .offline import object_supported
from .quotes import locate_quote
from .store import Store
from .util import word_count

_LEGAL = [
    (re.compile(r"\b(?:is|are|was|were)\s+(?:fully\s+)?compliant\b", re.I), "evidence suggests alignment (requires review)"),
    (re.compile(r"\bfully\s+compliant\b", re.I), "evidence suggests alignment (requires review)"),
    (re.compile(r"\bis\s+(?:hereby\s+)?approved\b", re.I), "is recommended for human review"),
    (re.compile(r"\b(?:we\s+)?approve[sd]?\s+(?:this\s+)?vendor\b", re.I), "recommend human review of this vendor"),
    (re.compile(r"\bguarantee[sd]?\b", re.I), "indicates"),
    (re.compile(r"\bsafe\s+to\s+(?:onboard|use)\b", re.I), "appears suitable subject to human review"),
    (re.compile(r"\bno\s+risk\b", re.I), "no risk identified in the evidence provided"),
    (re.compile(r"\b(?:is|are|was|were)\s+(?:in\s+)?(?:non-?\s?compliant|non-?\s?compliance|in\s+breach|in\s+violation)\b", re.I), "may have a gap against the requirement (requires review)"),
    (re.compile(r"\b(?:violates?|violated|breach(?:es|ed)?)\s+(?:the\s+)?(?:law|regulations?|gdpr|dora|act|statute)\b", re.I), "may not meet the requirement (requires review)"),
    (re.compile(r"\b(?:illegal|unlawful)\b", re.I), "possibly inconsistent with a requirement"),
]


def language_safety(text: str | None) -> tuple[str | None, bool]:
    """GR-018: agents never state legal conclusions. Rewrites and reports whether a rewrite happened."""
    if not text:
        return text, False
    changed = False
    for rx, repl in _LEGAL:
        new = rx.sub(repl, text)
        changed |= new != text
        text = new
    return text, changed


@dataclass
class ValidationReport:
    ok: bool
    result: AgentResult
    errors: list[str] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)
    rewritten: int = 0


def validate_claim_grounding(store: Store, tenant_id: str, vendor_id: str, claim: Claim) -> list[str]:
    errs = []
    if not claim.evidence:
        return ["claim has no evidence (R2)"]
    for ev in claim.evidence:
        if ev.quote and word_count(ev.quote) > 40:
            errs.append("quote exceeds 40 words (GR-003)")
        if ev.source_type == "document":
            doc = store.get("documents", "doc_id", ev.doc_id) if ev.doc_id else None
            if not doc or doc["tenant_id"] != tenant_id or doc["vendor_id"] != vendor_id:
                errs.append(f"cited document {ev.doc_id} not found for this tenant/vendor (GR-009)")
                continue
            if ev.chunk_id:
                ch = store.get("doc_chunks", "chunk_id", ev.chunk_id)
                if not ch or ch["doc_id"] != ev.doc_id:
                    errs.append(f"cited chunk {ev.chunk_id} does not resolve")
            if (ev.locator or "").startswith("absence:"):
                continue   # absence is verified against the whole document by the independent verifier
            pages = (doc["clean_text"] or "").split("\f")
            if not ev.quote:
                errs.append("document evidence requires a verbatim quote")
                continue
            score, page = locate_quote(pages, ev.quote)
            if page is None:
                errs.append(f"quote not found in cited document (best match {score}) (GR-003)")
                continue
            if ev.page is not None and ev.page != page:
                ev.page = page   # correct the page mechanically from the located quote
            elif ev.page is None:
                ev.page = page
            ok, why = object_supported(claim.predicate, claim.object, ev.quote, claim.subject)
            if not ok:
                errs.append(f"claimed value does not match the quoted passage ({why})")
        else:
            if not ev.locator or not ev.source_sha256:
                errs.append(f"{ev.source_type} evidence needs locator and source_sha256")
    return errs


def validate_result(store: Store, tenant_id: str, vendor_id: str, result: AgentResult) -> ValidationReport:
    keep, dropped, errors, rewritten = [], [], [], 0
    for c in result.claims:
        errs = validate_claim_grounding(store, tenant_id, vendor_id, c)
        if errs:
            dropped.append({"statement": c.statement, "predicate": c.predicate, "errors": errs})
            continue
        c.statement, ch = language_safety(c.statement)
        rewritten += int(ch)
        keep.append(c)
    for f in result.findings:
        for attr in ("title", "description", "remediation"):
            new, ch = language_safety(getattr(f, attr))
            setattr(f, attr, new)
            rewritten += int(ch)
    if dropped:
        errors.append(f"{len(dropped)} claim(s) dropped for failed grounding")
    result.claims = keep
    return ValidationReport(ok=not dropped, result=result, errors=errors, dropped=dropped, rewritten=rewritten)
