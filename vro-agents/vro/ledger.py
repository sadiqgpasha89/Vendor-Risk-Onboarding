"""Claim ledger = self-correcting memory (plan §6.4): claim -> evidence -> version -> detect -> verify -> correct.

* Memory stores evidence (document id, page, quote hash, source sha256, version), not just text.
* Staleness detection is deterministic (no LLM): ST-001..ST-010. Stale claims are flagged, never deleted (R5, GR-007).
* Only TRUSTED claims flow into scoring and packets. `get_claims(include_stale=False)` is the default tool contract.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from .models import Claim, Evidence
from .policy import PolicyEngine
from .quotes import locate_quote
from .store import Store
from .util import canonical_json, iso, new_id, now, parse_date, sha256_text, squash

ACTIVE = ("TRUSTED", "UNTRUSTED")
TIER_WEIGHT = {1: 8, 2: 4, 3: 2, 4: 1}


@dataclass
class StaleChange:
    claim_id: str
    rule: str
    reason: str


class Ledger:
    def __init__(self, store: Store, policy: PolicyEngine):
        self.store, self.policy = store, policy

    # ------------------------------------------------------------------ writes
    def create_claim(self, tenant_id: str, vendor_id: str, case_id: str | None, claim: Claim, produced_by: str,
                     prompt_version: str = "n/a", status: str = "UNTRUSTED") -> str:
        obj_json = canonical_json(claim.object)
        # idempotency: same atomic claim with the same primary evidence is not re-created
        for ex in self.store.query("SELECT claim_id, object FROM claims WHERE tenant_id=? AND vendor_id=? AND subject=? AND predicate=? "
                                   "AND status IN ('TRUSTED','UNTRUSTED','STALE')", (tenant_id, vendor_id, claim.subject, claim.predicate)):
            if canonical_json(ex["object"]) == obj_json:
                ev0 = self.store.query("SELECT source_sha256 FROM claim_evidence WHERE claim_id=?", (ex["claim_id"],))
                if ev0 and ev0[0]["source_sha256"] == claim.evidence[0].source_sha256:
                    return ex["claim_id"]
        cid = claim.claim_id or new_id("c_")
        ts = iso(now())
        with self.store.tx():
            self.store.insert("claims", {
                "claim_id": cid, "tenant_id": tenant_id, "vendor_id": vendor_id, "case_id": case_id, "subject": claim.subject,
                "predicate": claim.predicate, "object": claim.object, "statement": claim.statement, "status": status,
                "confidence": claim.confidence, "produced_by": produced_by, "prompt_version": prompt_version, "version": 1,
                "policy_version": self.policy.version, "valid_until": iso(claim.valid_until), "created_at": ts, "last_verified_at": None})
            for ev in claim.evidence:
                self._insert_evidence(cid, ev)
            self.store.insert("claim_versions", {"claim_id": cid, "version": 1, "statement": claim.statement, "status": status,
                                                 "changed_by": produced_by, "change_reason": "created", "changed_at": ts})
        return cid

    def _insert_evidence(self, claim_id: str, ev: Evidence) -> None:
        self.store.insert("claim_evidence", {
            "evidence_id": new_id("e_"), "claim_id": claim_id, "source_type": ev.source_type, "doc_id": ev.doc_id,
            "chunk_id": ev.chunk_id, "page": ev.page, "locator": ev.locator, "quote": ev.quote,
            "quote_hash": sha256_text(squash(ev.quote or "").casefold()) if ev.quote else None,
            "source_sha256": ev.source_sha256, "source_version": ev.source_version, "retrieved_at": iso(ev.retrieved_at), "stance": ev.stance})

    def set_status(self, claim_id: str, status: str, by: str, reason: str, stale_reason: str | None = None,
                   statement: str | None = None) -> None:
        c = self.store.get("claims", "claim_id", claim_id)
        if not c:
            raise KeyError(claim_id)
        ver = int(c["version"]) + 1
        ts = iso(now())
        with self.store.tx():
            self.store.update("claims", "claim_id", claim_id, {
                "status": status, "version": ver, "stale_reason": stale_reason if status == "STALE" else None,
                "last_verified_at": ts if status == "TRUSTED" else c.get("last_verified_at"),
                **({"statement": statement} if statement else {})})
            self.store.insert("claim_versions", {"claim_id": claim_id, "version": ver, "statement": statement or c["statement"],
                                                 "status": status, "changed_by": by, "change_reason": reason, "changed_at": ts})

    def add_evidence(self, claim_id: str, ev: Evidence, by: str = "system") -> None:
        self._insert_evidence(claim_id, ev)
        c = self.store.get("claims", "claim_id", claim_id)
        if ev.stance == "CONTRADICTS" and c and c["status"] == "TRUSTED":
            self.set_status(claim_id, "STALE", by, "contradicting evidence added", "ST-008: contradicting evidence added")

    def hard_delete(self, *_a, **_k):  # R5: stale != deleted
        raise PermissionError("claims are never hard-deleted; transition to REFUTED/SUPERSEDED instead")

    # ------------------------------------------------------------------ reads
    def evidence(self, claim_id: str) -> list[dict]:
        return self.store.query("SELECT * FROM claim_evidence WHERE claim_id=? ORDER BY retrieved_at", (claim_id,))

    def get_claims(self, tenant_id: str, vendor_id: str, case_id: str | None = None, predicate: str | None = None,
                   status: str | None = None, include_stale: bool = False, with_evidence: bool = False) -> list[dict]:
        sql, p = "SELECT * FROM claims WHERE tenant_id=? AND vendor_id=?", [tenant_id, vendor_id]
        if case_id:
            sql += " AND case_id=?"; p.append(case_id)
        if predicate:
            sql += " AND predicate=?"; p.append(predicate)
        if status:
            sql += " AND status=?"; p.append(status)
        else:
            allowed = ACTIVE + (("STALE",) if include_stale else ())
            sql += f" AND status IN ({','.join('?' * len(allowed))})"; p += list(allowed)
        rows = self.store.query(sql + " ORDER BY created_at", p)
        for r in rows:
            if r["status"] == "STALE":
                r["badge"] = "STALE / DON'T TRUST YET"
            elif r["status"] == "TRUSTED":
                r["badge"] = "TRUSTED"
            else:
                r["badge"] = r["status"]
            if with_evidence:
                r["evidence"] = self.evidence(r["claim_id"])
        return rows

    def trusted(self, tenant_id: str, vendor_id: str, case_id: str | None = None) -> list[dict]:
        return self.get_claims(tenant_id, vendor_id, case_id, status="TRUSTED", with_evidence=True)

    # ------------------------------------------------------------------ staleness (deterministic)
    def check_claim(self, c: dict, at: datetime | None = None, sources: dict | None = None) -> StaleChange | None:
        at = at or now()
        sources = sources or {}
        for ev in self.evidence(c["claim_id"]):
            if ev["stance"] != "SUPPORTS":
                continue
            if ev["source_type"] == "document" and ev["doc_id"]:
                doc = self.store.get("documents", "doc_id", ev["doc_id"])
                if not doc:
                    return StaleChange(c["claim_id"], "ST-003", "source document no longer present")
                newer = self.store.one("SELECT doc_id FROM documents WHERE supersedes_doc_id=?", (ev["doc_id"],))
                if newer:
                    return StaleChange(c["claim_id"], "ST-001", f"document superseded by {newer['doc_id']}")
                if doc["sha256"] != ev["source_sha256"]:
                    return StaleChange(c["claim_id"], "ST-003", "source hash changed")
            elif ev["source_type"] == "list":
                cur = sources.get(("list", ev["locator"]))
                if cur is not None and cur != ev["source_sha256"]:
                    return StaleChange(c["claim_id"], "ST-004", f"sanctions list updated ({ev['locator']})")
            elif ev["source_type"] == "api":
                cur = sources.get(("api", ev["locator"]))
                if cur is not None and cur != ev["source_sha256"]:
                    return StaleChange(c["claim_id"], "ST-003", f"source {ev['locator']} changed")
        vu = c.get("valid_until")
        if vu:
            vd = parse_date(vu)
            if vd and vd < at.date():
                return StaleChange(c["claim_id"], "ST-002", f"validity expired on {vd.isoformat()}")
        if c["predicate"].startswith(("mapping_", "regulatory_", "clause_")) and c.get("policy_version") != self.policy.version:
            return StaleChange(c["claim_id"], "ST-006", "policy pack version changed since claim was derived")
        created = datetime.fromisoformat(c.get("last_verified_at") or c["created_at"])
        if (at - created).days > self.policy.max_age_days(c["predicate"]):
            return StaleChange(c["claim_id"], "ST-007", f"older than {self.policy.max_age_days(c['predicate'])} days")
        return None

    def run_staleness(self, tenant_id: str, vendor_id: str | None = None, at: datetime | None = None,
                      sources: dict | None = None, by: str = "A11:memory_steward") -> list[StaleChange]:
        sql, p = "SELECT * FROM claims WHERE tenant_id=? AND status='TRUSTED'", [tenant_id]
        if vendor_id:
            sql += " AND vendor_id=?"; p.append(vendor_id)
        changes = []
        for c in self.store.query(sql, p):
            ch = self.check_claim(c, at, sources)
            if ch:
                self.set_status(c["claim_id"], "STALE", by, ch.reason, f"{ch.rule}: {ch.reason}")
                changes.append(ch)
        return changes

    def _bulk_stale(self, rows: list[dict], rule: str, reason: str, by: str) -> list[StaleChange]:
        out = []
        for c in rows:
            if c["status"] == "TRUSTED":
                self.set_status(c["claim_id"], "STALE", by, reason, f"{rule}: {reason}")
                out.append(StaleChange(c["claim_id"], rule, reason))
        return out

    def on_ownership_change(self, tenant_id: str, vendor_id: str, by: str = "A11:memory_steward"):   # ST-005
        rows = self.store.query("SELECT * FROM claims WHERE tenant_id=? AND vendor_id=? AND (predicate LIKE 'ownership%' OR predicate LIKE 'screening%')",
                                (tenant_id, vendor_id))
        return self._bulk_stale(rows, "ST-005", "LEI/ownership change", by)

    def on_prompt_recalled(self, tenant_id: str, prompt_version: str, by: str = "A11:memory_steward"):   # ST-009
        rows = self.store.query("SELECT * FROM claims WHERE tenant_id=? AND prompt_version=?", (tenant_id, prompt_version))
        return self._bulk_stale(rows, "ST-009", f"prompt/model {prompt_version} recalled", by)

    def on_material_change(self, tenant_id: str, vendor_id: str, kind: str, by: str = "A11:memory_steward"):   # ST-010
        rows = self.store.query("SELECT * FROM claims WHERE tenant_id=? AND vendor_id=?", (tenant_id, vendor_id))
        return self._bulk_stale(rows, "ST-010", f"material change event: {kind}", by)

    # ------------------------------------------------------------------ correction in the flow of work
    def verify_claim(self, tenant_id: str, claim_id: str, by: str = "A11:memory_steward") -> dict:
        """Re-verify a STALE/UNTRUSTED claim against the CURRENT source. Confirmed -> TRUSTED (new version, fresh evidence).
        Contradicted -> REFUTED. Cannot decide offline (e.g. list rescreen, no newer doc) -> stays STALE + needs_human."""
        c = self.store.get("claims", "claim_id", claim_id)
        if not c or c["tenant_id"] != tenant_id:
            return {"result": "not_found"}
        evs = [e for e in self.evidence(claim_id) if e["stance"] == "SUPPORTS" and e["source_type"] == "document" and e["quote"]]
        if not evs:
            return {"result": "needs_human", "reason": "no re-checkable document evidence (list/api/human source)"}
        ev = evs[0]
        doc = self.store.get("documents", "doc_id", ev["doc_id"])
        # follow supersession chain to the current document
        cur = doc
        while cur:
            newer = self.store.one("SELECT * FROM documents WHERE supersedes_doc_id=?", (cur["doc_id"],))
            if not newer:
                break
            cur = newer
        if not cur:
            return {"result": "needs_human", "reason": "source document missing"}
        pages = (cur["clean_text"] or "").split("\f")
        score, page = locate_quote(pages, ev["quote"])
        if page is not None:
            new_ev = Evidence(source_type="document", doc_id=cur["doc_id"], page=page, locator=ev["locator"], quote=ev["quote"],
                              source_sha256=cur["sha256"], source_version=str(cur.get("version") or 1))
            self._insert_evidence(claim_id, new_ev)
            self.set_status(claim_id, "TRUSTED", by, f"re-verified against current document {cur['doc_id']} p.{page} (match {score})")
            return {"result": "confirmed", "doc_id": cur["doc_id"], "page": page, "score": score}
        if cur["doc_id"] != ev["doc_id"]:
            # a newer document exists and no longer contains the supporting passage -> claim must be re-extracted from it
            self.set_status(claim_id, "SUPERSEDED", by, f"supporting passage not found in superseding document {cur['doc_id']}; re-extract")
            return {"result": "superseded", "doc_id": cur["doc_id"]}
        self.set_status(claim_id, "REFUTED", by, "supporting passage no longer present in source")
        return {"result": "refuted"}

    # ------------------------------------------------------------------ metrics
    def stale_debt(self, tenant_id: str) -> dict:
        rows = self.store.query(
            "SELECT c.vendor_id, c.claim_id, c.created_at, c.last_verified_at, v.tier FROM claims c LEFT JOIN vendor v ON v.vendor_id=c.vendor_id "
            "WHERE c.tenant_id=? AND c.status='STALE'", (tenant_id,))
        by_vendor: dict[str, dict] = {}
        for r in rows:
            d = by_vendor.setdefault(r["vendor_id"], {"stale_claims": 0, "weighted": 0})
            d["stale_claims"] += 1
            d["weighted"] += TIER_WEIGHT.get(r["tier"] or 3, 2)
        return {"total_stale": len(rows), "weighted_debt": sum(d["weighted"] for d in by_vendor.values()), "by_vendor": by_vendor}
