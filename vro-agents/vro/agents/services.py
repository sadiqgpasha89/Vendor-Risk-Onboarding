"""Service container: wires store, policy, scoring, ledger, retrieval, gateway, screening list and the guarded tool registry."""
from __future__ import annotations

import json
from pathlib import Path

from ..config import ROOT, Settings
from ..ledger import Ledger
from ..llm_gateway import Gateway
from ..policy import PolicyEngine
from ..retrieval import RetrievalIndex
from ..scoring import ScoringEngine
from ..screening import SanctionsList
from ..embeddings import make_embedder
from ..store import Store, make_store
from ..tools import Tool, ToolContext, ToolRegistry
from ..util import iso, new_id, now

# Least privilege per agent (plan §6.1). A4 (Reader) has NO tools (GR-008).
ALLOWED_TOOLS: dict[str, frozenset] = {
    "A0": frozenset({"get_policy_plan"}),
    "A1": frozenset({"get_policy_plan"}),
    "A2": frozenset({"get_screening_results"}),
    "A3": frozenset({"get_policy_plan"}),
    "A4": frozenset(),
    "A5": frozenset({"search_chunks", "get_claims", "get_doc_inventory", "get_policy_plan"}),
    "A6": frozenset({"search_chunks", "get_claims", "get_doc_inventory"}),
    "A7": frozenset({"search_chunks", "get_claims", "get_doc_inventory", "get_policy_plan"}),
    "A8": frozenset({"get_claims", "get_doc_inventory", "get_portfolio_view"}),
    "A9": frozenset({"get_claims"}),
    "A10": frozenset({"get_claims", "get_doc_chunk"}),
    "A11": frozenset({"get_claims", "verify_claim"}),
    "A12": frozenset({"get_doc_inventory", "get_policy_plan", "draft_comms"}),
}


class Services:
    def __init__(self, settings: Settings | None = None, store: Store | None = None, gateway: Gateway | None = None,
                 sanctions: SanctionsList | None = None):
        self.settings = settings or Settings()
        self.store = store or make_store(self.settings)
        self.policy = PolicyEngine(self.settings.policy_dir, self.settings.policy_pack)
        self.scoring = ScoringEngine(self.policy.scoring)
        self.ledger = Ledger(self.store, self.policy)
        self.retrieval = RetrievalIndex(self.store, make_embedder(self.settings))
        self.gateway = gateway or Gateway(self.settings, self.store)
        self.sanctions = sanctions or self._default_list()
        self.tools = ToolRegistry(self.store)
        self._register_tools()

    def _default_list(self) -> SanctionsList:
        p = Path(ROOT / "data" / "synth" / "sanctions_list.json")
        return SanctionsList.load(str(p)) if p.exists() else SanctionsList("SYNTHETIC_SDN", [])

    def reload_policy(self, pack: str | None = None) -> None:
        self.policy.reload(pack)
        self.scoring = ScoringEngine(self.policy.scoring)
        self.ledger.policy = self.policy

    # ------------------------------------------------------------------ tool implementations (read-mostly)
    def _register_tools(self) -> None:
        R = self.tools.register
        R(Tool("search_chunks", lambda c, query, k=8, doc_types=None: [h.__dict__ for h in self.retrieval.search(c.tenant_id, c.vendor_id, query, k=k, doc_types=doc_types)],
               description="Hybrid retrieval over this vendor's current documents"))
        R(Tool("get_claims", lambda c, include_stale=False, predicate=None, status=None: self.ledger.get_claims(
            c.tenant_id, c.vendor_id, None, predicate, status, include_stale, with_evidence=True),
               description="Claim ledger; stale claims excluded unless include_stale=True"))
        R(Tool("get_doc_inventory", lambda c: self.doc_inventory(c.tenant_id, c.vendor_id)))
        R(Tool("get_policy_plan", lambda c: self.case_plan(c.case_id)))
        R(Tool("get_screening_results", lambda c: self.store.query("SELECT * FROM screening_results WHERE tenant_id=? AND case_id=?", (c.tenant_id, c.case_id))))
        R(Tool("get_doc_chunk", lambda c, chunk_id: self.retrieval.get_chunk(c.tenant_id, c.vendor_id, chunk_id)))
        R(Tool("get_portfolio_view", lambda c: self.portfolio_intakes(c.tenant_id, c.case_id)))
        R(Tool("verify_claim", lambda c, claim_id: self.ledger.verify_claim(c.tenant_id, claim_id), writes=True,
               description="Re-verify a claim against its current source (A11)"))
        R(Tool("draft_comms", lambda c, kind, context: self._draft(c, kind, context), writes=True,
               description="Create a DRAFT message. Drafts cannot be sent by any agent."))

    def _draft(self, c: ToolContext, kind: str, context: dict) -> dict:
        from ..llm_gateway import LLMRequest
        from ..validators import language_safety
        from .prompts import COMMS, system_for
        resp = self.gateway.complete(LLMRequest(task="comms.draft", system=system_for("A12 Comms Drafter", COMMS, today=now().date(), policy_version=self.policy.version,
                                                                                       tenant_id=c.tenant_id, case_id=c.case_id),
                                                 user=json.dumps(context, default=str), tier="mid", agent="A12", case_id=c.case_id,
                                                 context={**context, "kind": kind}))
        body, _ = language_safety(resp.data["body"])
        did = new_id("dr_")
        self.store.insert("drafts", {"draft_id": did, "tenant_id": c.tenant_id, "case_id": c.case_id, "kind": kind, "body": body,
                                     "status": "DRAFT", "created_at": iso(now())})
        return {"draft_id": did}

    # ------------------------------------------------------------------ shared reads
    def case(self, case_id: str) -> dict:
        c = self.store.get("cases", "case_id", case_id)
        if not c:
            raise KeyError(case_id)
        c["context"] = c.get("context") or {}
        return c

    def case_plan(self, case_id: str) -> dict:
        c = self.case(case_id)
        tier = c["final_tier"] or c["proposed_tier"] or 2
        return self.policy.plan(tier, c["jurisdictions"] or [])

    def current_docs(self, tenant_id: str, vendor_id: str) -> list[dict]:
        return self.store.query(
            "SELECT * FROM documents WHERE tenant_id=? AND vendor_id=? AND quarantine_status='ACCEPTED' "
            "AND doc_id NOT IN (SELECT supersedes_doc_id FROM documents WHERE supersedes_doc_id IS NOT NULL) ORDER BY uploaded_at",
            (tenant_id, vendor_id))

    def doc_inventory(self, tenant_id: str, vendor_id: str) -> list[dict]:
        return [{k: d[k] for k in ("doc_id", "doc_type", "filename", "sha256", "period_end", "valid_until", "uploaded_at", "hidden_text_flag", "page_count", "ocr_quality")}
                for d in self.current_docs(tenant_id, vendor_id)]

    def portfolio_intakes(self, tenant_id: str, exclude_case: str) -> list[dict]:
        rows = self.store.query("SELECT intake FROM cases WHERE tenant_id=? AND case_id<>? AND state IN ('ONBOARDED','MONITORING')", (tenant_id, exclude_case))
        return [r["intake"] for r in rows]

    def new_ctx(self, case: dict, agent: str, run_id: str, tainted: bool = False) -> ToolContext:
        return ToolContext(tenant_id=case["tenant_id"], case_id=case["case_id"], vendor_id=case["vendor_id"], agent=agent, run_id=run_id,
                           allowed=ALLOWED_TOOLS.get(agent, frozenset()), registry=self.tools, tainted=tainted)
