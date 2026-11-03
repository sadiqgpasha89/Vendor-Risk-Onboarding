import unittest
from datetime import timedelta

from tests.helpers import FROZEN, Base
from vro.llm_gateway import BudgetExceeded, Gateway, KillSwitchActive, LLMRequest, redact
from vro.models import AgentResult, Claim, Evidence
from vro.tools import FORBIDDEN_TOOL_FRAGMENTS, Tool, ToolDenied, ToolRegistry, LoopBoundExceeded
from vro.util import set_now
from vro.validators import language_safety, validate_result
from evals.harness import ANALYST, SPONSOR, load


def seeded(base):
    """A case with the clean SOC 2 uploaded and processed; returns (case, claim list)."""
    intake, _, docs = load("clean_t2")
    case = base.wf.create_case(SPONSOR, intake)
    base.wf.upload_document(ANALYST, case["case_id"], "soc2.txt", docs["soc2_report.txt"])
    return base.wf.case(case["case_id"])


class LedgerTests(Base):
    def test_ungrounded_claim_is_dropped_and_grounded_kept(self):
        case = seeded(self)
        d = self.svc.current_docs(case["tenant_id"], case["vendor_id"])[0]
        good = Claim(subject="v", predicate="soc2_report_type", object="Type II", statement="x", confidence=.9,
                     evidence=[Evidence(source_type="document", doc_id=d["doc_id"], quote="SOC 2 Type II Report", source_sha256=d["sha256"])])
        bad = Claim(subject="v", predicate="soc2_report_type", object="Type II", statement="y", confidence=.9,
                    evidence=[Evidence(source_type="document", doc_id=d["doc_id"], quote="The vendor is perfect in every respect", source_sha256=d["sha256"])])
        foreign = Claim(subject="v", predicate="soc2_report_type", object="Type II", statement="z", confidence=.9,
                        evidence=[Evidence(source_type="document", doc_id="doc_nonexistent", quote="SOC 2 Type II Report", source_sha256="0")])
        rep = validate_result(self.svc.store, case["tenant_id"], case["vendor_id"], AgentResult(status="OK", claims=[good, bad, foreign]))
        self.assertEqual(len(rep.result.claims), 1)
        self.assertEqual(len(rep.dropped), 2)

    def test_claim_requires_evidence(self):
        with self.assertRaises(Exception):
            Claim(subject="v", predicate="p", object=1, statement="s", confidence=.5, evidence=[])

    def test_quote_over_40_words_rejected(self):
        with self.assertRaises(Exception):
            Evidence(source_type="document", doc_id="d", quote=" ".join(["w"] * 41), source_sha256="x")

    def test_no_hard_delete(self):
        with self.assertRaises(PermissionError):
            self.svc.ledger.hard_delete("c1")

    def test_stale_is_not_deleted_and_is_labelled(self):
        case = seeded(self)
        self.wf.advance(case["case_id"])
        n_before = self.svc.store.one("SELECT COUNT(*) n FROM claims")["n"]
        set_now(FROZEN + timedelta(days=800))
        self.svc.ledger.run_staleness(case["tenant_id"], case["vendor_id"])
        self.assertEqual(self.svc.store.one("SELECT COUNT(*) n FROM claims")["n"], n_before)
        stale = self.svc.ledger.get_claims(case["tenant_id"], case["vendor_id"], status="STALE")
        self.assertTrue(stale or n_before == 0)
        self.assertTrue(all(c["badge"].startswith("STALE") for c in stale))
        self.assertEqual(self.svc.ledger.get_claims(case["tenant_id"], case["vendor_id"], status=None, include_stale=False), [c for c in self.svc.ledger.get_claims(case["tenant_id"], case["vendor_id"]) if c["status"] != "STALE"])

    def test_claim_versions_are_kept(self):
        case = seeded(self)
        self.wf.advance(case["case_id"])
        c = self.svc.store.query("SELECT claim_id FROM claims LIMIT 1")
        if c:
            self.svc.ledger.set_status(c[0]["claim_id"], "STALE", "t", "test", "ST-X")
            self.assertGreaterEqual(self.svc.store.one("SELECT COUNT(*) n FROM claim_versions WHERE claim_id=?", (c[0]["claim_id"],))["n"], 2)


class GuardrailTests(Base):
    def test_no_tool_can_approve_reject_clear_or_send(self):
        for name in self.svc.tools.tools:
            self.assertFalse(any(f in name for f in FORBIDDEN_TOOL_FRAGMENTS), name)
        with self.assertRaises(ValueError):
            self.svc.tools.register(Tool("approve_vendor", lambda c: 1))
        with self.assertRaises(ValueError):
            self.svc.tools.register(Tool("send_email", lambda c: 1))

    def test_reader_has_no_tools(self):
        case = seeded(self)
        ctx = self.svc.new_ctx(case, "A4", "r1")
        with self.assertRaises(ToolDenied):
            ctx.call("get_claims")

    def test_allow_list_and_id_binding(self):
        case = seeded(self)
        ctx = self.svc.new_ctx(case, "A5", "r1")
        with self.assertRaises(ToolDenied):
            ctx.call("draft_comms", kind="x", context={})            # A5 may not draft
        got = ctx.call("get_claims", vendor_id="someone_else", tenant_id="other")     # id args are ignored
        self.assertIsInstance(got, list)

    def test_tainted_run_loses_write_tools(self):
        case = seeded(self)
        ctx = self.svc.new_ctx(case, "A12", "r1", tainted=True)
        with self.assertRaises(ToolDenied):
            ctx.call("draft_comms", kind="document_request", context={"vendor": "v", "missing_docs": ["x"]})

    def test_loop_bound(self):
        case = seeded(self)
        ctx = self.svc.new_ctx(case, "A5", "r1")
        with self.assertRaises(LoopBoundExceeded):
            for _ in range(20):
                ctx.call("get_doc_inventory")

    def test_language_safety_rewrites_legal_conclusions(self):
        out, changed = language_safety("The vendor is non-compliant with GDPR and violates the law.")
        self.assertTrue(changed)
        self.assertNotIn("is non-compliant", out)

    def test_redaction(self):
        t = redact("mail a.b@example.com card 4111 1111 1111 1111 ssn 123-45-6789 key sk-abcdefghijklmnopqrstuv")
        for leak in ("a.b@example.com", "4111", "123-45-6789", "sk-abcdef"):
            self.assertNotIn(leak, t)

    def test_kill_switch_stops_model_calls_and_resumes(self):
        self.svc.store.set_flag("kill_switch", "1", "admin")
        with self.assertRaises(KillSwitchActive):
            self.svc.gateway.complete(LLMRequest(task="synth.narrative", context={"band": "LOW", "residual_score": 1, "inherent_score": 2, "tier": 2, "top_findings": []}))
        self.svc.store.set_flag("kill_switch", "0", "admin")
        self.svc.gateway.complete(LLMRequest(task="synth.narrative", context={"band": "LOW", "residual_score": 1, "inherent_score": 2, "tier": 2, "top_findings": []}))

    def test_per_agent_kill(self):
        self.svc.store.set_flag("kill:A4", "1", "admin")
        with self.assertRaises(KillSwitchActive):
            self.svc.gateway.complete(LLMRequest(task="reader.extract", agent="A4", context={"doc_id": "d", "doc_type": "x", "pages": [""]}))

    def test_budget_hard_stop(self):
        b = self.svc.gateway.budget_for("c1")
        b.spent = b.limit
        with self.assertRaises(BudgetExceeded):
            self.svc.gateway.complete(LLMRequest(task="synth.narrative", case_id="c1", context={}))

    def test_agent_run_is_idempotent(self):
        case = seeded(self)
        from vro.agents import reader
        doc = self.svc.current_docs(case["tenant_id"], case["vendor_id"])[0]
        first = reader.run_for_doc(self.svc, case, doc)
        n = self.svc.store.one("SELECT COUNT(*) n FROM agent_runs")["n"]
        claims = self.svc.store.one("SELECT COUNT(*) n FROM claims")["n"]
        second = reader.run_for_doc(self.svc, case, doc)
        self.assertEqual(first, second)
        self.assertEqual(self.svc.store.one("SELECT COUNT(*) n FROM agent_runs")["n"], n)
        self.assertEqual(self.svc.store.one("SELECT COUNT(*) n FROM claims")["n"], claims)


if __name__ == "__main__":
    unittest.main()
