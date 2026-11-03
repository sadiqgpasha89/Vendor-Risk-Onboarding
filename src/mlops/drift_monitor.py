"""MLOps Drift Monitoring: Covariate Shift (PSI, Wasserstein) and Concept Drift."""

import logging
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime
import numpy as np
import pandas as pd
from scipy.stats import wasserstein_distance

logger = logging.getLogger(__name__)


@dataclass
class FeatureDriftReport:
    feature_name: str
    psi_score: float
    wasserstein_dist: float
    drift_status: str  # STABLE, MODERATE_DRIFT, SEVERE_DRIFT
    baseline_mean: float
    current_mean: float


@dataclass
class DriftSummaryReport:
    total_features_evaluated: int
    features_with_drift: List[str]
    max_psi: float
    overall_status: str  # STABLE, WARNING, CRITICAL
    feature_reports: List[FeatureDriftReport]
    evaluated_at: datetime = field(default_factory=datetime.utcnow)


class DriftMonitor:
    """Computes Population Stability Index (PSI) and statistical drift across feature distributions."""

    def __init__(
        self,
        psi_warning_threshold: float = 0.10,
        psi_critical_threshold: float = 0.25,
        psi_threshold: Optional[float] = None,
    ):
        self.psi_warning_threshold = psi_warning_threshold
        self.psi_critical_threshold = psi_threshold if psi_threshold is not None else psi_critical_threshold

    @staticmethod
    def calculate_psi(baseline: np.ndarray, current: np.ndarray, num_bins: int = 10) -> float:
        """Calculate Population Stability Index (PSI) between baseline and current distributions."""
        baseline = baseline[~np.isnan(baseline)]
        current = current[~np.isnan(current)]

        if len(baseline) == 0 or len(current) == 0:
            return 0.0

        # Create quantile-based or uniform bins
        min_val = min(np.min(baseline), np.min(current))
        max_val = max(np.max(baseline), np.max(current))

        if min_val == max_val:
            return 0.0

        bins = np.linspace(min_val, max_val, num_bins + 1)

        # Count frequencies
        base_counts, _ = np.histogram(baseline, bins=bins)
        curr_counts, _ = np.histogram(current, bins=bins)

        # Convert to percentages with epsilon smoothing to prevent div by zero
        eps = 1e-4
        base_pct = (base_counts + eps) / (len(baseline) + eps * num_bins)
        curr_pct = (curr_counts + eps) / (len(current) + eps * num_bins)

        # PSI formula: sum((Actual% - Expected%) * ln(Actual% / Expected%))
        psi_val = np.sum((curr_pct - base_pct) * np.log(curr_pct / base_pct))
        return float(np.clip(psi_val, 0.0, 10.0))

    def evaluate_feature_drift(
        self,
        baseline_df: pd.DataFrame,
        current_df: pd.DataFrame,
        features: Optional[List[str]] = None,
    ) -> DriftSummaryReport:
        """Compare current inference traffic against training baseline dataset."""
        if features is None:
            # Common numeric features
            num_cols = baseline_df.select_dtypes(include=[np.number]).columns
            features = [c for c in num_cols if c in current_df.columns]

        reports: List[FeatureDriftReport] = []
        drifted_features = []
        max_psi = 0.0

        for feat in features:
            b_vals = baseline_df[feat].dropna().values
            c_vals = current_df[feat].dropna().values

            if len(b_vals) < 5 or len(c_vals) < 5:
                continue

            psi = self.calculate_psi(b_vals, c_vals)
            w_dist = float(wasserstein_distance(b_vals, c_vals))

            max_psi = max(max_psi, psi)

            if psi >= self.psi_critical_threshold:
                status = "SEVERE_DRIFT"
                drifted_features.append(feat)
            elif psi >= self.psi_warning_threshold:
                status = "MODERATE_DRIFT"
                drifted_features.append(feat)
            else:
                status = "STABLE"

            reports.append(
                FeatureDriftReport(
                    feature_name=feat,
                    psi_score=round(psi, 4),
                    wasserstein_dist=round(w_dist, 4),
                    drift_status=status,
                    baseline_mean=round(float(np.mean(b_vals)), 4),
                    current_mean=round(float(np.mean(c_vals)), 4),
                )
            )

        if max_psi >= self.psi_critical_threshold:
            overall_status = "CRITICAL"
        elif max_psi >= self.psi_warning_threshold:
            overall_status = "WARNING"
        else:
            overall_status = "STABLE"

        return DriftSummaryReport(
            total_features_evaluated=len(reports),
            features_with_drift=drifted_features,
            max_psi=round(max_psi, 4),
            overall_status=overall_status,
            feature_reports=reports,
        )

    def detect_drift(
        self,
        baseline: Any,
        current: Any,
        features: Optional[List[str]] = None,
    ) -> DriftSummaryReport:
        """Detect drift between baseline and current data (accepts DataFrames or lists of dicts)."""
        base_df = pd.DataFrame(baseline) if isinstance(baseline, list) else baseline
        curr_df = pd.DataFrame(current) if isinstance(current, list) else current
        report = self.evaluate_feature_drift(base_df, curr_df, features)
        # Add dynamic attributes for caller convenience
        report.feature_metrics = {r.feature_name: r for r in report.feature_reports}
        report.drift_detected = len(report.features_with_drift) > 0
        report.summary = f"Drift Status: {report.overall_status}, Max PSI: {report.max_psi}, Drifted: {report.features_with_drift}"
        return report
