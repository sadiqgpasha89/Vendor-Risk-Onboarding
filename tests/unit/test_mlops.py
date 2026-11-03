"""Unit tests for MLOps Subsystem: Model Registry, Drift Monitoring, and Pre-Deployment Validation."""

import pytest
import numpy as np
from src.mlops.model_registry import ModelRegistry, ModelStage
from src.mlops.drift_monitor import DriftMonitor
from src.mlops.evaluation_pipeline import MLModelEvaluator
from src.mlops.synthetic_data import SyntheticVendorDataGenerator


@pytest.mark.unit
class TestModelRegistry:
    """Test suite for versioned model governance and stage lifecycle."""

    def setup_method(self):
        self.registry = ModelRegistry()

    def test_register_and_retrieve_model(self):
        metadata = self.registry.register_model(
            model_name="vendor_risk_gbdt",
            version="1.2.0",
            model_type="lightgbm_gbdt",
            metrics={"auc_pr": 0.84, "brier_score": 0.07},
            feature_names=["tax_id_valid", "bank_change_within_72h"],
        )
        assert metadata.version == "1.2.0"
        assert metadata.stage == ModelStage.DRAFT

    def test_stage_transition_lifecycle(self):
        self.registry.register_model(
            model_name="vendor_risk_anomaly",
            version="2.0.0",
            model_type="isolation_forest",
            metrics={"f1": 0.78},
            feature_names=["f1", "f2"],
        )
        # Transition to staging
        staged = self.registry.transition_stage("vendor_risk_anomaly", "2.0.0", ModelStage.STAGING)
        assert staged.stage == ModelStage.STAGING

        # Promote to production
        prod = self.registry.transition_stage("vendor_risk_anomaly", "2.0.0", ModelStage.PRODUCTION)
        assert prod.stage == ModelStage.PRODUCTION

        # Retrieve active production model
        active = self.registry.get_production_model("vendor_risk_anomaly")
        assert active is not None
        assert active.version == "2.0.0"


@pytest.mark.unit
class TestDriftMonitoring:
    """Test suite for Population Stability Index (PSI) and Wasserstein distance."""

    def setup_method(self):
        self.monitor = DriftMonitor(psi_warning_threshold=0.25, psi_critical_threshold=0.50)

    def test_stable_distribution_no_drift(self):
        rng = np.random.RandomState(42)
        base_vals = rng.normal(10.0, 2.0, 500)
        curr_vals = base_vals + rng.normal(0.0, 0.05, 500)
        baseline = [{"feature_x": float(v)} for v in base_vals]
        current = [{"feature_x": float(v)} for v in curr_vals]

        report = self.monitor.detect_drift(baseline, current, features=["feature_x"])
        assert report.drift_detected is False
        assert report.feature_metrics["feature_x"].psi_score < 0.25

    def test_shifted_distribution_drift_detected(self):
        rng = np.random.RandomState(42)
        # Shift mean from 10 to 30 to simulate significant distribution shift
        baseline = [{"feature_x": float(v)} for v in rng.normal(10.0, 2.0, 200)]
        current = [{"feature_x": float(v)} for v in rng.normal(30.0, 5.0, 200)]

        report = self.monitor.detect_drift(baseline, current, features=["feature_x"])
        assert report.drift_detected is True
        assert report.feature_metrics["feature_x"].drift_status in ("SEVERE_DRIFT", "MODERATE_DRIFT")


@pytest.mark.unit
class TestModelEvaluationPipeline:
    """Test suite for pre-deployment SLA criteria and quality gate validation."""

    def setup_method(self):
        self.evaluator = MLModelEvaluator(
            min_auc_pr=0.70,
            max_brier_score=0.20,
            min_f1=0.65,
            max_latency_ms=250.0,
        )

    def test_passing_candidate_model(self):
        report = self.evaluator.evaluate_candidate("candidate_v2", n_samples=100)
        assert report.passed is True
        assert len(report.blocking_reasons) == 0
        assert report.auc_pr >= 0.70
        assert report.p99_latency_ms <= 250.0

    def test_failing_candidate_model_on_bad_metrics(self):
        # Ground truth vs random bad predictions
        rng = np.random.RandomState(42)
        y_true = np.array([1, 1, 1, 1, 0, 0, 0, 0] * 10)
        y_probs = np.array([0.05, 0.05, 0.05, 0.05, 0.95, 0.95, 0.95, 0.95] * 10)  # Inverted predictions
        latencies = [15.0] * 80

        report = self.evaluator.evaluate_model(
            model_name="inverted_model",
            version="0.1.0",
            y_true=y_true,
            y_probs=y_probs,
            inference_latencies_ms=latencies,
        )
        assert report.passed is False
        assert len(report.blocking_reasons) > 0


@pytest.mark.unit
class TestSyntheticDataGenerator:
    """Test suite for synthetic fraud and clean vendor benchmark generator."""

    def test_generate_benchmark_suite(self):
        suite = SyntheticVendorDataGenerator.generate_benchmark_suite(num_samples=20, fraud_ratio=0.25)
        assert len(suite) == 20

        fraud_cases = [s for s in suite if s["expected_label"] == 1]
        clean_cases = [s for s in suite if s["expected_label"] == 0]
        assert len(fraud_cases) == 5
        assert len(clean_cases) == 15
