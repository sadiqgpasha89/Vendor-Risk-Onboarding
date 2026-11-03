from vro.store import DB_ERRORS
import unittest
from datetime import timedelta

from evals.harness import AML, ANALYST, APPROVERS, SENIOR, SPONSOR, TENANT, drive, load
from tests.helpers import FROZEN, Base
from vro.models import GateDecision as GD
from vro.policy import PolicyError
from vro.util import new_id, now
from vro.workflow import Actor, NotFound


def dec(d, why="reviewed and agreed with the evidence", **kw):
    return GD(decision=d, rationale=why, **kw)


class HappyPath(Base):
    def test_clean_t2_reaches_monitoring_with_trusted_claims_only(self):
        r = drive(self.svc, self.wf, "clean_t2")
        self.assertEqual(r["state"], "MONITORING")
        self.assertEqual(set(r["claims"]), {"TRUSTED"})
        self.assertEqual(r["band"], "LOW")
        self.assertTrue(self.svc.store.verify_audit_chain()["ok"])
        # every gate decision in the record belongs to a human actor
        for a in self.svc.store.query("SELECT approver_id FROM approvals"):
            self.assertTrue(a["approver_id"].startswith("u_"))

    def test_findings_all_cite_claims_with_evidence(self):
        r = drive(self.svc, self.wf, "contract_gaps", finish=False)
        for f in self.svc.store.query("SELECT claim_ids FROM findings WHERE status='OPEN'"):
            self.assertTrue(f["claim_ids"])
            for cid in f["claim_ids"]:
                self.assertTrue(self.svc.ledger.evidence(cid))

    def test_missing_docs_create_drafts_but_nothing_is_sent(self):
        intake, _, docs = load("clean_t2")
        c = self.wf.create_case(SPONSOR, intake)
        self.wf.decide_gate(SENIOR, c["case_id"], "G2", dec("CONFIRM"))
        self.assertEqual(self.wf.case(c["case_id"])["state"], "DUE_DILIGENCE")
        drafts = self.svc.store.query("SELECT * FROM drafts WHERE case_id=?", (c["case_id"],))
        self.assertTrue(drafts)
        self.assertTrue(all(d["status"] == "DRAFT" and "NOT SENT" in d["body"] for d in drafts))


class Gates(Base):
    def test_role_enforced_on_every_gate(self):
        intake, _, docs = load("clean_t2")
        c = self.wf.create_case(SPONSOR, intake)
        with self.assertRaises(PolicyError) as e:
            self.wf.decide_gate(ANALYST, c["case_id"], "G2", dec("CONFIRM"))       # needs senior_analyst
        self.assertEqual(e.exception.code, "E_ROLE")
        with self.assertRaises(PolicyError):
            self.wf.create_case(ANALYST, intake)                                       # analysts cannot raise requests

    def test_g2_override_needs_rationale_and_sets_tier(self):
        intake, _, _ = load("clean_t2")
        c = self.wf.create_case(SPONSOR, intake)
        with self.assertRaises(PolicyError):
            self.wf.decide_gate(SENIOR, c["case_id"], "G2", GD(decision="OVERRIDE", override_tier=1, rationale="because"))
        self.wf.decide_gate(SENIOR, c["case_id"], "G2", GD(decision="OVERRIDE", override_tier=1, rationale="business-critical payment rail, tier up"))
        self.assertEqual(self.wf.case(c["case_id"])["final_tier"], 1)

    def test_sanctions_block_tiering_until_aml_dispositions(self):
        intake, _, _ = load("sanctions_near_miss")
        intake["declared_owners"] = [{"name": "Dmitri Valkenrov", "pct": 70, "country_iso2": "RU", "is_person": True}]
        c = self.wf.create_case(SPONSOR, intake)
        cid = c["case_id"]
        self.assertEqual(c["state"], "HUMAN_SCREEN_REVIEW")
        self.assertEqual(c["proposed_tier"], None)                  # tiering has not run
        rows = self.svc.store.query("SELECT * FROM screening_results WHERE case_id=? AND auto_disposition='POTENTIAL_MATCH'", (cid,))
        self.assertTrue(rows)
        with self.assertRaises(PolicyError) as e:
            self.wf.decide_screening(ANALYST, cid, rows[0]["screening_id"], "CLEAR", "I think it is fine, honestly")
        self.assertEqual(e.exception.code, "E_ROLE")
        with self.assertRaises(PolicyError) as e:
            self.wf.decide_screening(AML, cid, rows[0]["screening_id"], "CLEAR", "ok")
        self.assertEqual(e.exception.code, "E_RATIONALE")
        for r in rows[:-1]:
            self.wf.decide_screening(AML, cid, r["screening_id"], "CLEAR", "different person, DOB and country do not match")
        self.assertEqual(self.wf.case(cid)["state"], "HUMAN_SCREEN_REVIEW")         # one still open
        self.wf.decide_screening(AML, cid, rows[-1]["screening_id"], "CLEAR", "different person, DOB and country do not match")
        self.assertEqual(self.wf.case(cid)["state"], "TIERING")

    def test_confirmed_match_rejects_vendor(self):
        r = drive(self.svc, self.wf, "sanctions_true_match")
        self.assertEqual(r["state"], "REJECTED")
        self.assertEqual(self.svc.store.one("SELECT COUNT(*) n FROM agent_runs WHERE agent='A3'")["n"], 0)
        self.assertEqual(self.svc.store.one("SELECT status FROM vendor WHERE vendor_id=(SELECT vendor_id FROM cases LIMIT 1)")["status"], "REJECTED")

    def test_segregation_of_duties_requester_and_preparer(self):
        intake, _, _ = load("clean_t2")
        req = Actor("u_dual", "sponsor", TENANT)
        c = self.wf.create_case(req, intake)
        cid = c["case_id"]
        drive_to_review(self, cid)
        prep = Actor("u_prep", "senior_analyst", TENANT)
        self.wf.decide_gate(prep, cid, "G3", dec("APPROVE"))
        self.wf.complete_contracting(ANALYST, cid)
        with self.assertRaises(PolicyError) as e:
            self.wf.decide_gate(Actor("u_dual", "senior_risk", TENANT), cid, "G4", dec("APPROVE"))      # approver == requester
        self.assertEqual(e.exception.code, "E_SOD")
        with self.assertRaises(PolicyError) as e:
            self.wf.decide_gate(Actor("u_prep", "senior_risk", TENANT), cid, "G4", dec("APPROVE"))      # approver == preparer
        self.assertEqual(e.exception.code, "E_SOD")
        with self.assertRaises(PolicyError) as e:
            self.wf.decide_gate(Actor("u_m", "manager", TENANT), cid, "G4", dec("APPROVE"))             # T2 needs senior_risk or committee
        self.assertEqual(e.exception.code, "E_ROLE")
        self.assertEqual(self.wf.decide_gate(Actor("u_ok", "senior_risk", TENANT), cid, "G4", dec("APPROVE"))["state"], "MONITORING")

    def test_open_critical_finding_blocks_approval_until_excepted(self):
        intake, _, _ = load("clean_t2")
        c = self.wf.create_case(SPONSOR, intake)
        cid = c["case_id"]
        drive_to_review(self, cid)
        fid = new_id("f_")
        self.svc.store.insert("findings", {"finding_id": fid, "tenant_id": TENANT, "case_id": cid, "domain": "security", "severity": "CRITICAL", "title": "Test critical",
                                           "description": "d", "claim_ids": ["x"], "regulation_refs": [], "status": "OPEN", "rule_id": "T-1", "created_at": "2026-10-24"})
        with self.assertRaises(PolicyError) as e:
            self.wf.decide_gate(ANALYST, cid, "G3", dec("APPROVE"))
        self.assertEqual(e.exception.code, "E_CRITICAL_OPEN")
        with self.assertRaises(PolicyError):
            self.wf.disposition_finding(ANALYST, cid, fid, "ACCEPT_RISK", "accepting this for now please", "2026-12-01")   # analyst cannot accept CRITICAL
        with self.assertRaises(PolicyError):
            self.wf.disposition_finding(Actor("u_sr", "senior_risk", TENANT), cid, fid, "ACCEPT_RISK", "compensating control in place", None)   # needs expiry
        self.wf.disposition_finding(Actor("u_sr", "senior_risk", TENANT), cid, fid, "ACCEPT_RISK", "compensating control in place", "2026-12-01")
        self.assertEqual(self.wf.decide_gate(ANALYST, cid, "G3", dec("APPROVE"))["state"], "CONTRACTING")

    def test_conditional_approval_expiry_is_capped_at_30_days(self):
        intake, _, _ = load("clean_t2")
        c = self.wf.create_case(SPONSOR, intake)
        cid = c["case_id"]
        drive_to_review(self, cid)
        self.wf.decide_gate(SENIOR, cid, "G3", dec("APPROVE"))
        self.wf.complete_contracting(ANALYST, cid)
        too_late = (now().date() + timedelta(days=45)).isoformat()
        with self.assertRaises(PolicyError) as e:
            self.wf.decide_gate(APPROVERS[2], cid, "G4", GD(decision="APPROVE", rationale="conditional", conditions=["provide pentest"], expires_at=too_late))
        self.assertEqual(e.exception.code, "E_CONDITIONAL_EXPIRY")
        ok = (now().date() + timedelta(days=25)).isoformat()
        self.wf.decide_gate(APPROVERS[2], cid, "G4", GD(decision="APPROVE", rationale="conditional", conditions=["provide pentest"], expires_at=ok))
        self.assertEqual(self.wf.case(cid)["conditional_expires"][:10], ok)


class Emergency(Base):
    def _case(self):
        intake, _, _ = load("clean_t2")
        c = self.wf.create_case(SPONSOR, {**intake, "emergency": True})
        self.wf.decide_gate(SENIOR, c["case_id"], "G2", dec("CONFIRM"))
        return c["case_id"]

    def test_emergency_needs_head_of_tprm_and_30_day_cap(self):
        cid = self._case()
        head = Actor("u_head", "head_tprm", TENANT)
        with self.assertRaises(PolicyError):
            self.wf.request_emergency(SENIOR, cid, GD(decision="APPROVE", rationale="urgent business need", expires_at="2026-11-10"))
        with self.assertRaises(PolicyError) as e:
            self.wf.request_emergency(head, cid, GD(decision="APPROVE", rationale="urgent business need", expires_at="2027-03-01"))
        self.assertEqual(e.exception.code, "E_CONDITIONAL_EXPIRY")
        self.wf.request_emergency(head, cid, GD(decision="APPROVE", rationale="urgent business need", expires_at="2026-11-10"))
        self.assertEqual(self.wf.case(cid)["conditional_expires"][:10], "2026-11-10")
        self.assertEqual(self.svc.store.one("SELECT status FROM vendor WHERE vendor_id=(SELECT vendor_id FROM cases WHERE case_id=?)", (cid,))["status"], "CONDITIONAL")

    def test_emergency_is_refused_for_non_emergency_case_and_expires(self):
        intake, _, _ = load("clean_t2")
        c = self.wf.create_case(SPONSOR, intake)
        self.wf.decide_gate(SENIOR, c["case_id"], "G2", dec("CONFIRM"))
        with self.assertRaises(PolicyError):
            self.wf.request_emergency(Actor("u_head", "head_tprm", TENANT), c["case_id"], GD(decision="APPROVE", rationale="not an emergency", expires_at="2026-11-10"))
        cid = self._case()
        self.wf.request_emergency(Actor("u_head", "head_tprm", TENANT), cid, GD(decision="APPROVE", rationale="urgent business need", expires_at="2026-11-10"))
        from vro.util import set_now
        set_now(FROZEN + timedelta(days=40))
        res = self.wf.sweep(TENANT)
        self.assertIn(cid, res["conditional_expired"])


class Changes(Base):
    def test_duplicate_and_unsupported_uploads(self):
        intake, _, docs = load("clean_t2")
        c = self.wf.create_case(SPONSOR, intake)
        cid = c["case_id"]
        a = self.wf.upload_document(ANALYST, cid, "s.txt", docs["soc2_report.txt"])
        b = self.wf.upload_document(ANALYST, cid, "s_copy.txt", docs["soc2_report.txt"])
        self.assertTrue(b["duplicate"])
        self.assertEqual(a["doc_id"], b["doc_id"])
        p = self.wf.upload_document(ANALYST, cid, "x.pdf", b"%PDF-1.4 fake")
        self.assertEqual(p["status"], "REJECTED")                                     # corrupt PDF: quarantined with a reason, nothing crashes
        self.assertTrue(p["reason"])
        self.svc.settings.pdf_ocr = False                                             # a scan we cannot read -> analyst is asked for another format
        scan = __import__("tests.pdfmaker", fromlist=["x"]).scanned_pdf(["Total current assets: $500,000"])
        u = self.wf.upload_document(ANALYST, cid, "scan.pdf", scan)
        self.assertEqual(u["status"], "UNSUPPORTED_PARSER")
        self.assertTrue(self.svc.store.query("SELECT * FROM questions WHERE case_id=? AND text LIKE '%scan.pdf%'", (cid,)))
        z = self.wf.upload_document(ANALYST, cid, "x.zip", b"PK\x03\x04junk")
        self.assertEqual(z["status"], "REJECTED")

    def test_new_evidence_after_review_sends_case_back_and_returns(self):
        r = drive(self.svc, self.wf, "clean_t2", finish=False)
        cid = r["case_id"]
        self.assertEqual(self.wf.case(cid)["state"], "HUMAN_REVIEW")
        _, _, docs = load("clean_t2")
        new = docs["soc2_report.txt"].decode().replace("CUEC-1:", "Exception noted: CC6.3 - Terminated users retained access for 14 days\nCUEC-1:").encode()
        out = self.wf.upload_document(ANALYST, cid, "soc2_v2.txt", new)
        self.assertIsNotNone(out["supersedes"])
        self.assertEqual(self.wf.case(cid)["state"], "HUMAN_REVIEW")
        rules = {f["rule_id"] for f in self.svc.store.query("SELECT rule_id FROM findings WHERE case_id=? AND status='OPEN'", (cid,))}
        self.assertIn("SEC-006", rules)
        self.assertTrue(self.svc.store.query("SELECT 1 FROM findings WHERE case_id=? AND status='SUPERSEDED'", (cid,)))      # earlier pass kept, not deleted

    def test_dispute_is_recorded_and_carried_over(self):
        r = drive(self.svc, self.wf, "soc2_exception_cc6", finish=False)
        cid = r["case_id"]
        f = next(x for x in self.svc.store.query("SELECT * FROM findings WHERE case_id=? AND status='OPEN'", (cid,)) if x["rule_id"] == "SEC-006")
        self.wf.dispute_finding(ANALYST, cid, f["finding_id"], "management response already accepted")
        self.assertEqual(self.svc.store.one("SELECT COUNT(*) n FROM feedback WHERE kind='finding_dispute'")["n"], 1)


class Isolation(Base):
    def test_tenant_isolation(self):
        intake, _, _ = load("clean_t2")
        c = self.wf.create_case(SPONSOR, intake)
        other = Actor("u_x", "analyst", "t_other")
        with self.assertRaises(NotFound):
            self.wf._scoped(c["case_id"], other)
        with self.assertRaises(NotFound):
            self.wf.upload_document(other, c["case_id"], "a.txt", b"hello")

    def test_audit_log_is_append_only_and_chained(self):
        drive(self.svc, self.wf, "clean_t2", finish=False)
        self.assertTrue(self.svc.store.verify_audit_chain()["ok"])
        with self.assertRaises(DB_ERRORS):
            self.svc.store.execute("UPDATE audit_events SET actor='x' WHERE seq=1")
        with self.assertRaises(DB_ERRORS):
            self.svc.store.execute("DELETE FROM audit_events WHERE seq=1")


def drive_to_review(test, cid):
    _, _, docs = load("clean_t2")
    for n, b in docs.items():
        test.wf.upload_document(ANALYST, cid, n, b)
    case = test.wf.case(cid)
    if case["state"] == "TIERING":
        test.wf.decide_gate(SENIOR, cid, "G2", dec("CONFIRM"))
    case = test.wf.advance(cid)
    assert case["state"] == "HUMAN_REVIEW", case["state"]


if __name__ == "__main__":
    unittest.main()
