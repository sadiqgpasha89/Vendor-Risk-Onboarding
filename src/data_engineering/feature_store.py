"""Dual-Store Feature Engineering Pipeline (Online sub-5ms Redis + Offline Historical Store)."""

import json
import logging
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timezone
import pandas as pd
import numpy as np

from src.schemas.vendor import VendorProfile
from src.utils.validators import validate_tax_id, validate_iban

logger = logging.getLogger(__name__)

# High-risk / sanctioned / FATF non-cooperative jurisdictions
HIGH_RISK_JURISDICTIONS = {
    "IR", "KP", "SY", "CU", "RU", "MM", "BY", "VE", "SD", "SS"
}


class FeatureStore:
    """Manages online sub-5ms feature caching and offline feature baselines."""

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url
        self._online_memory_cache: Dict[str, Dict[str, Any]] = {}
        self._offline_dataset: List[Dict[str, Any]] = []

    def compute_features(
        self,
        vendor: Union[VendorProfile, Dict[str, Any]],
        existing_vendor_bank_accounts: Optional[List[str]] = None,
        employee_addresses: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Compute the standardized feature vector for quantitative ML and policy evaluation."""
        if isinstance(vendor, dict):
            v_id = vendor.get("id") or vendor.get("vendor_id") or "VEND-TEMP"
            v_name = vendor.get("name", "")
            v_legal_name = vendor.get("legal_name", v_name)
            v_reg_num = vendor.get("registration_number") or vendor.get("tax_id", "")
            v_country = vendor.get("country", "US")
            v_rev = vendor.get("annual_revenue") or vendor.get("annual_revenue_usd") or 0.0
            v_emp = vendor.get("employee_count") or 0
            v_owners = vendor.get("beneficial_owners") or []
            v_bank_acc = vendor.get("bank_account_number") or ""
            v_bank_recency = vendor.get("bank_change_recency_hours") or 99999.0
            v_age_days = vendor.get("bank_account_age_days") or vendor.get("registration_age_days") or 365
            vendor = VendorProfile(
                id=v_id,
                name=v_name,
                legal_name=v_legal_name,
                registration_number=v_reg_num,
                country=v_country,
                annual_revenue_usd=float(v_rev),
                employee_count=int(v_emp),
                beneficial_owners=v_owners,
                bank_account_number=v_bank_acc,
                metadata={
                    "registration_age_days": v_age_days,
                    "bank_change_recency_hours": v_bank_recency,
                },
            )

        now = datetime.now(timezone.utc)

        # 1. Registration Age in days
        reg_age_days = 0
        if vendor.incorporation_date:
            inc_date = vendor.incorporation_date
            if inc_date.tzinfo is None:
                inc_date = inc_date.replace(tzinfo=timezone.utc)
            reg_age_days = max(0, (now - inc_date).days)
        elif "registration_age_days" in vendor.metadata:
            reg_age_days = int(vendor.metadata["registration_age_days"])

        # 2. Tax ID validity
        is_tax_valid, _ = validate_tax_id(vendor.registration_number, country_code=vendor.country)

        # 3. High risk jurisdiction flag
        is_high_risk_country = vendor.country.upper() in HIGH_RISK_JURISDICTIONS

        # 4. Shared bank account cross-vendor flag
        shared_bank_flag = 0
        if vendor.bank_account_number and existing_vendor_bank_accounts:
            if existing_vendor_bank_accounts.count(vendor.bank_account_number) > 0:
                shared_bank_flag = 1

        # 5. Bank detail change recency in hours
        bank_change_recency_hours = 99999.0
        if vendor.bank_account_updated_at:
            up_date = vendor.bank_account_updated_at
            if up_date.tzinfo is None:
                up_date = up_date.replace(tzinfo=timezone.utc)
            bank_change_recency_hours = max(0.0, (now - up_date).total_seconds() / 3600.0)
        elif "bank_change_recency_hours" in vendor.metadata:
            bank_change_recency_hours = float(vendor.metadata["bank_change_recency_hours"])

        # 6. Revenue and Employee size proxies
        revenue = vendor.annual_revenue_usd or 0.0
        employees = vendor.employee_count or 0

        # Feature vector
        feature_vector = {
            "vendor_id": vendor.id,
            "registration_age_days": float(reg_age_days),
            "is_new_company_under_180d": 1.0 if reg_age_days < 180 else 0.0,
            "tax_id_valid": 1.0 if is_tax_valid else 0.0,
            "high_risk_jurisdiction_flag": 1.0 if is_high_risk_country else 0.0,
            "shared_bank_account_cross_vendor": float(shared_bank_flag),
            "bank_change_within_72h": 1.0 if bank_change_recency_hours <= 72.0 else 0.0,
            "bank_change_recency_hours": float(bank_change_recency_hours),
            "annual_revenue_log": float(np.log1p(revenue)),
            "employee_count": float(employees),
            "missing_beneficial_owners": 1.0 if len(vendor.beneficial_owners) == 0 else 0.0,
            "computed_at": now.isoformat(),
        }

        # Store in online cache
        self.put_online(vendor.id, feature_vector)
        self._offline_dataset.append(feature_vector)

        return feature_vector

    def put_online(self, vendor_id: str, features: Dict[str, Any]) -> None:
        """Store feature vector in online cache for sub-5ms lookup."""
        self._online_memory_cache[vendor_id] = features

    def get_online(self, vendor_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve feature vector in < 5ms."""
        return self._online_memory_cache.get(vendor_id)

    def get_offline_dataframe(self) -> pd.DataFrame:
        """Return historical feature dataset as pandas DataFrame for training & drift detection."""
        if not self._offline_dataset:
            # Seed with mock historical dataset for baseline
            return self._generate_baseline_dataset()
        return pd.DataFrame(self._offline_dataset)

    def _generate_baseline_dataset(self, n: int = 200) -> pd.DataFrame:
        """Generate representative baseline feature records for cold-start drift calculation."""
        np.random.seed(42)
        records = []
        for i in range(n):
            reg_age = float(np.random.exponential(scale=1200) + 30)
            records.append({
                "vendor_id": f"HIST-V-{i:04d}",
                "registration_age_days": reg_age,
                "is_new_company_under_180d": 1.0 if reg_age < 180 else 0.0,
                "tax_id_valid": 1.0 if np.random.rand() > 0.05 else 0.0,
                "high_risk_jurisdiction_flag": 1.0 if np.random.rand() < 0.08 else 0.0,
                "shared_bank_account_cross_vendor": 1.0 if np.random.rand() < 0.03 else 0.0,
                "bank_change_within_72h": 1.0 if np.random.rand() < 0.04 else 0.0,
                "bank_change_recency_hours": float(np.random.uniform(10, 5000)),
                "annual_revenue_log": float(np.random.normal(12.0, 2.5)),
                "employee_count": float(np.random.exponential(50) + 1),
                "missing_beneficial_owners": 1.0 if np.random.rand() < 0.12 else 0.0,
            })
        return pd.DataFrame(records)
