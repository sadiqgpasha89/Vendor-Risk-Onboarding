"""Unit tests for Data Science Subsystem: Tier 1 Deterministic Rules, Tier 2 ML Scorer, and Hybrid Risk Engine."""

import pytest
from datetime import datetime, timezone, timedelta

from src.schemas.vendor import VendorProfile, VendorRiskTier
from src.schemas.assessment import ActionRecommendation
from src.datascience.tier1_rules.engine import Tier1RuleEngine
from src.datascience.tier2_ml.scorer import QuantitativeRiskScorer
from src.datascience.hybrid_engine import HybridRiskEngine
from src.data_engineering.feature_store import FeatureStore


@pytest.mark.unit
class TestTier1Rules:
    """Test suite for Tier 1 deterministic statutory policy engine."""

    def setup_method(self):
        self.rule_engine = Tier1RuleEngine()

    def test_sanctioned_entity_hard_block(self):
        vendor = VendorProfile(
            id="V-SANC-1",
            name="Rosneft Oil Company",
            legal_name="Rosneft Oil Company",
            registration_number="RU7706107510",
            country="RU",
        )
        features = {
            "bank_change_within_72h": 0.0,
            "tax_id_valid": 1.0,
            "shared_bank_account_cross_vendor": 0.0,
            "missing_beneficial_owners": 0.0,
        }
        violations = self.rule_engine.evaluate_rules(vendor, features)

        assert len(violations) >= 1
        rule_ids = [v.rule_id for v in violations]
        assert "RULE-RBS-001" in rule_ids or "RULE-RBS-002" in rule_ids
        assert any(v.severity in ("HARD_BLOCK", "CRITICAL_HOLD") for v in violations)

    def test_bank_change_within_72h_critical_hold(self):
        vendor = VendorProfile(
            id="V-BANK-1",
            name="Alpha Supplies LLC",
            legal_name="Alpha Supplies LLC",
            registration_number="12-3456789",
            country="US",
        )
        features = {
            "bank_change_within_72h": 1.0,
            "bank_change_recency_hours": 12.0,
            "tax_id_valid": 1.0,
            "shared_bank_account_cross_vendor": 0.0,
            "missing_beneficial_owners": 0.0,
        }
        violations = self.rule_engine.evaluate_rules(vendor, features)

        bank_violations = [v for v in violations if v.rule_id == "RULE-RBS-004"]
        assert len(bank_violations) == 1
        assert bank_violations[0].severity == "CRITICAL_HOLD"

    def test_invalid_tax_identity(self):
        vendor = VendorProfile(
            id="V-TAX-1",
            name="Beta Consulting",
            legal_name="Beta Consulting Inc",
            registration_number="BAD-TAX-9999",
            country="US",
        )
        features = {
            "tax_id_valid": 0.0,
            "bank_change_within_72h": 0.0,
            "shared_bank_account_cross_vendor": 0.0,
            "missing_beneficial_owners": 0.0,
        }
        violations = self.rule_engine.evaluate_rules(vendor, features)
        tax_violations = [v for v in violations if v.rule_id == "RULE-RBS-005"]
        assert len(tax_violations) == 1

    def test_clean_vendor_no_violations(self):
        vendor = VendorProfile(
            id="V-CLEAN-1",
            name="Valid Enterprise Corp",
            legal_name="Valid Enterprise Corporation",
            registration_number="12-3456789",
            country="US",
            beneficial_owners=["John Doe", "Jane Smith"],
        )
        features = {
            "tax_id_valid": 1.0,
            "bank_change_within_72h": 0.0,
            "bank_change_recency_hours": 5000.0,
            "shared_bank_account_cross_vendor": 0.0,
            "missing_beneficial_owners": 0.0,
        }
        violations = self.rule_engine.evaluate_rules(vendor, features)
        assert len(violations) == 0


@pytest.mark.unit
class TestTier2MLScorer:
    """Test suite for Tier 2 quantitative anomaly and GBDT risk scorer."""

    def setup_method(self):
        self.scorer = QuantitativeRiskScorer()

    def test_prediction_output_structure(self):
        sample_features = {
            "registration_age_days": 720.0,
            "is_new_company_under_180d": 0.0,
            "tax_id_valid": 1.0,
            "high_risk_jurisdiction_flag": 0.0,
            "shared_bank_account_cross_vendor": 0.0,
            "bank_change_within_72h": 0.0,
            "bank_change_recency_hours": 4000.0,
            "annual_revenue_log": 16.0,
            "employee_count": 120.0,
            "missing_beneficial_owners": 0.0,
        }
        result = self.scorer.predict_risk(sample_features)

        assert 0.0 <= result.calibrated_risk_probability <= 1.0
        assert 1 <= result.risk_decile <= 10
        assert len(result.top_risk_drivers) + len(result.top_mitigating_factors) > 0
        assert result.model_name is not None

    def test_high_risk_feature_anomaly(self):
        # Shell company / high risk pattern
        high_risk_features = {
            "registration_age_days": 10.0,
            "is_new_company_under_180d": 1.0,
            "tax_id_valid": 0.0,
            "high_risk_jurisdiction_flag": 1.0,
            "shared_bank_account_cross_vendor": 1.0,
            "bank_change_within_72h": 1.0,
            "bank_change_recency_hours": 6.0,
            "annual_revenue_log": 10.0,
            "employee_count": 1.0,
            "missing_beneficial_owners": 1.0,
        }
        result = self.scorer.predict_risk(high_risk_features)
        assert result.calibrated_risk_probability >= 0.50
        assert result.risk_decile >= 6


@pytest.mark.unit
class TestHybridRiskEngine:
    """Test suite for Tri-Tier Hybrid Risk Engine."""

    def setup_method(self):
        self.engine = HybridRiskEngine()

    def test_critical_statutory_rule_overrides_low_ml(self):
        # Even if vendor looks statistically benign, hard sanction match forces CRITICAL
        sanctioned_vendor = {
            "id": "V-SANC-2",
            "name": "Rosneft Oil Company",
            "legal_name": "Rosneft Oil Company",
            "registration_number": "RU7706107510",
            "country": "RU",
            "annual_revenue": 50000000.0,
            "employee_count": 5000,
            "bank_account_age_days": 1000,
        }
        res = self.engine.evaluate_sync(sanctioned_vendor)

        assert res.risk_tier == VendorRiskTier.CRITICAL
        assert res.decision == ActionRecommendation.REJECT
        assert res.composite_score >= 95.0
        assert res.hitl_required is True

    def test_clean_vendor_auto_approval(self):
        clean_vendor = {
            "id": "V-CLEAN-2",
            "name": "Reliable Software Solutions",
            "legal_name": "Reliable Software Solutions Inc",
            "registration_number": "12-3456789",
            "country": "US",
            "annual_revenue": 10000000.0,
            "employee_count": 50,
            "bank_account_age_days": 800,
            "beneficial_owners": ["Alice Cooper", "Bob Dylan"],
        }
        res = self.engine.evaluate_sync(clean_vendor)

        assert res.risk_tier == VendorRiskTier.LOW
        assert res.decision == ActionRecommendation.AUTO_APPROVE
        assert res.composite_score < 35.0
        assert res.hitl_required is False

    def test_dict_and_profile_compatibility(self):
        vendor_dict = {
            "name": "Test Vendor Corp",
            "registration_number": "99-1234567",
            "country": "US",
            "annual_revenue": 2000000.0,
        }
        res = self.engine.evaluate_sync(vendor_dict)
        assert res.composite_score is not None
        assert res.risk_tier is not None
        assert "composite_score" in res.to_dict()
