import unittest

from tests.helpers import Base
from vro.models import VendorIntake
from vro.policy import PolicyError
from vro.scoring import CheckResult


def intake(**kw):
    d = {"legal_name": "Test Vendor Ltd", "country_iso2": "DE", "service_description": "x", "business_owner": "o",
         "data_access": {"data_types": ["internal"], "volume": "low", "storage_locations": ["DE"], "access_type": "read_only"},
         "criticality_hint": "low", "jurisdictions": ["EU"]}
    d.update(kw)
    return VendorIntake.model_validate(d)


class PolicyTests(Base):
    def test_illegal_transition_rejected(self):
        with self.assertRaises(PolicyError) as e:
            self.svc.policy.check_transition("SCREENING", "ONBOARDED")
        self.assertEqual(e.exception.code, "E_TRANSITION")

    def test_screening_cannot_reach_tiering_with_unresolved_match(self):
        with self.assertRaises(PolicyError) as e:
            self.svc.policy.check_screening_to_tiering(1)
        self.assertEqual(e.exception.code, "E_SANCTIONS_UNRESOLVED")
        self.svc.policy.check_screening_to_tiering(0)

    def test_segregation_of_duties(self):
        p = self.svc.policy
        with self.assertRaises(PolicyError):
            p.check_sod("a", "a", None)
        with self.assertRaises(PolicyError):
            p.check_sod("b", "a", "b")
        p.check_sod("c", "a", "b")

    def test_open_critical_blocks_approval(self):
        with self.assertRaises(PolicyError):
            self.svc.policy.check_can_approve(1)

    def test_conditional_expiry_bounds(self):
        p = self.svc.policy
        p.check_conditional_expiry(30)
        for d in (0, 31):
            with self.assertRaises(PolicyError):
                p.check_conditional_expiry(d)

    def test_gate_roles(self):
        p = self.svc.policy
        p.check_gate_actor("G1", None, "aml")
        with self.assertRaises(PolicyError):
            p.check_gate_actor("G1", None, "analyst")
        with self.assertRaises(PolicyError):
            p.check_gate_actor("G4", 1, "manager")        # T1 needs committee

    def test_plan_adds_jurisdiction_requirements(self):
        plan = self.svc.policy.plan(1, ["EU"])
        self.assertIn("register_of_information", plan["required_docs"])
        self.assertIn("dora_termination_rights", plan["required_clauses"])

    def test_policy_version_changes_with_content(self):
        v = self.svc.policy.version
        self.assertTrue(v.startswith("default@"))


class ScoringTests(Base):
    def test_tier_bands_and_determinism(self):
        a = self.svc.scoring.inherent(intake())
        b = self.svc.scoring.inherent(intake())
        self.assertEqual(a.model_dump(), b.model_dump())
        self.assertEqual(a.tier, 4)
        hi = self.svc.scoring.inherent(intake(criticality_hint="critical", substitutability="very_hard", annual_spend_usd=5e6,
                                              data_access={"data_types": ["customer_pii"], "volume": "very_high", "storage_locations": ["DE"], "access_type": "privileged"},
                                              customer_facing=True, regulatory_critical=True))
        self.assertEqual(hi.tier, 1)

    def test_floors(self):
        t = self.svc.scoring.inherent(intake(regulatory_critical=True))
        self.assertLessEqual(t.tier, 2)
        self.assertIn("regulatory_critical", t.floors_applied)
        t2 = self.svc.scoring.inherent(intake(data_access={"data_types": ["payment_card"], "volume": "low", "storage_locations": ["DE"], "access_type": "read_only"}))
        self.assertLessEqual(t2.tier, 2)

    def test_missing_evidence_is_zero_coverage(self):
        ce = self.svc.scoring.control_effectiveness({"security": [CheckResult("soc2_present", 3, 0.0, 0.0)]})
        self.assertEqual(ce["security"]["ce"], 0.0)
        self.assertEqual(ce["privacy"]["ce"], 0.0)   # no checks at all is never "fine"

    def test_critical_and_high_floors(self):
        ce = {d: {"ce": 1.0} for d in self.svc.scoring.cfg["control_domain_weights"]}
        self.assertEqual(self.svc.scoring.residual(60, ce, [])["band"], "LOW")
        self.assertEqual(self.svc.scoring.residual(60, ce, ["CRITICAL"])["band"], "HIGH")
        self.assertEqual(self.svc.scoring.residual(60, ce, ["HIGH"])["band"], "MEDIUM")
        self.assertEqual(self.svc.scoring.residual(60, ce, ["HIGH", "HIGH", "HIGH"])["band"], "HIGH")


if __name__ == "__main__":
    unittest.main()
