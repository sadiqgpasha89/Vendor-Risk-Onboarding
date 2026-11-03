"""A11 Memory Steward: deterministic staleness sweep over TRUSTED claims (R5: stale != deleted) and optional re-verification."""
from __future__ import annotations

from ..util import now
from .services import Services


def sweep(svc: Services, tenant_id: str, vendor_id: str | None = None) -> list[dict]:
    changes = svc.ledger.run_staleness(tenant_id, vendor_id)
    for ch in changes:
        svc.store.audit(tenant_id, "A11", "agent", "CLAIM_STALE", "claim", ch.claim_id, {"rule": ch.rule, "reason": ch.reason})
    return [{"claim_id": c.claim_id, "rule": c.rule, "reason": c.reason} for c in changes]
