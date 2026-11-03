"""Unit tests for Data Engineering Subsystem: Entity Resolution, Watchlists, Feature Store, and Ingestion."""

import pytest
from src.data_engineering.entity_resolution import EntityResolutionEngine
from src.data_engineering.watchlist_pipeline import WatchlistPipeline
from src.data_engineering.feature_store import FeatureStore
from src.data_engineering.document_pipeline import DocumentIngestionPipeline
from src.utils.validators import validate_tax_id, validate_iban, validate_swift_bic


@pytest.mark.unit
class TestEntityResolution:
    """Test suite for phonetic, Jaro-Winkler, and token-based entity resolution."""

    def setup_method(self):
        self.engine = EntityResolutionEngine(fuzzy_threshold=0.85)

    def test_corporate_suffix_normalization(self):
        norm1 = self.engine.normalize_entity_name("Acme Logistics Corporation")
        norm2 = self.engine.normalize_entity_name("Acme Logistics Corp.")
        norm3 = self.engine.normalize_entity_name("ACME LOGISTICS INC")
        assert norm1 == "acme logistics"
        assert norm2 == "acme logistics"
        assert norm3 == "acme logistics"

    def test_soundex_phonetic_matching(self):
        code1 = self.engine.soundex("Robert")
        code2 = self.engine.soundex("Rupert")
        assert code1 == code2  # R163

    def test_jaro_winkler_similarity(self):
        score_exact = self.engine.jaro_winkler("Acme Technologies", "Acme Technologies")
        score_close = self.engine.jaro_winkler("Acme Technologies", "Acme Technologis")
        score_diff = self.engine.jaro_winkler("Acme Technologies", "Zebra Zoo")

        assert score_exact == 1.0
        assert score_close >= 0.90
        assert score_diff < 0.60

    def test_registry_matching(self):
        known_registry = [
            {"id": "REG-1", "name": "Global Maritime Logistics Inc", "tax_id": "11-2233445"},
            {"id": "REG-2", "name": "Apex Cyber Defense Ltd", "tax_id": "99-8877665"},
        ]
        matches = self.engine.match_against_registry("Global Maritime Logistics Corp", known_registry=known_registry)
        assert len(matches) >= 1
        assert matches[0].target_id == "REG-1"
        assert matches[0].similarity_score >= 0.90


@pytest.mark.unit
class TestWatchlistPipeline:
    """Test suite for Sanctions and PEP Watchlist screening."""

    def setup_method(self):
        self.pipeline = WatchlistPipeline(fuzzy_threshold=0.85)

    def test_exact_sanctions_hit(self):
        res = self.pipeline.screen_entity("Rosneft Oil Company", country="RU")
        assert res.has_hit is True
        assert res.highest_match_score >= 0.95
        assert len(res.matches) >= 1
        assert res.matches[0].list_name == "OFAC_SDN"

    def test_fuzzy_sanctions_hit(self):
        res = self.pipeline.screen_entity("Huawei Technologys Company", country="CN")
        assert res.has_hit is True
        assert res.highest_match_score >= 0.85

    def test_clean_vendor_no_hit(self):
        res = self.pipeline.screen_entity("Innocent Local Bakery LLC", country="US")
        assert res.has_hit is False
        assert len(res.matches) == 0


@pytest.mark.unit
class TestFeatureStore:
    """Test suite for dual online sub-5ms / offline historical feature store."""

    def setup_method(self):
        self.store = FeatureStore()

    def test_feature_computation_and_caching(self):
        vendor_dict = {
            "id": "VEND-100",
            "name": "Prime Suppliers",
            "registration_number": "12-3456789",
            "country": "US",
            "annual_revenue": 5000000.0,
            "employee_count": 45,
            "bank_account_age_days": 400,
        }
        features = self.store.compute_features(vendor_dict)

        assert features["vendor_id"] == "VEND-100"
        assert features["tax_id_valid"] == 1.0
        assert features["high_risk_jurisdiction_flag"] == 0.0
        assert features["is_new_company_under_180d"] == 0.0

        # Verify online sub-5ms memory lookup
        cached = self.store.get_online("VEND-100")
        assert cached is not None
        assert cached["vendor_id"] == "VEND-100"

    def test_offline_dataframe_export(self):
        df = self.store.get_offline_dataframe()
        assert not df.empty
        assert "tax_id_valid" in df.columns
        assert "bank_change_within_72h" in df.columns


@pytest.mark.unit
class TestValidators:
    """Test suite for business data and banking validators."""

    def test_tax_id_validation(self):
        valid_us, _ = validate_tax_id("12-3456789", "US")
        invalid_us, _ = validate_tax_id("123", "US")
        valid_uk, _ = validate_tax_id("GB123456789", "GB")

        assert valid_us is True
        assert invalid_us is False
        assert valid_uk is True

    def test_iban_mod97_checksum(self):
        # Valid test IBAN (GB82 WEST 1234 5698 7654 32)
        valid_iban, _ = validate_iban("GB82WEST12345698765432")
        invalid_iban, _ = validate_iban("GB00WEST12345698765432")

        assert valid_iban is True
        assert invalid_iban is False

    def test_swift_bic_validation(self):
        valid_bic, _ = validate_swift_bic("CHASUS33")
        invalid_bic, _ = validate_swift_bic("12345")

        assert valid_bic is True
        assert invalid_bic is False
