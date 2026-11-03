"""Synthetic Edge-Case Dataset Generator for Vendor Risk & Fraud Scenarios."""

import random
from typing import List, Dict, Any
from datetime import datetime, timedelta
from src.schemas.vendor import VendorProfile, VendorRiskTier, VendorOnboardingStatus


class SyntheticVendorDataGenerator:
    """Generates synthetic vendor risk datasets for cold-start evaluation, load testing, and CI/CD."""

    @staticmethod
    def generate_benchmark_suite(num_samples: int = 50, fraud_ratio: float = 0.20) -> List[Dict[str, Any]]:
        """Generate balanced benchmark cases containing clean vendors, shell entities, and sanctions hits."""
        random.seed(42)
        suite = []
        num_fraud = int(num_samples * fraud_ratio)
        num_clean = num_samples - num_fraud

        # 1. Clean Vendors
        clean_names = ["Apex Logistics", "Beacon Analytics", "Crestview Software", "Delta Consulting", "Echo Hardware", "Fortis Security", "Global Freight", "Harbor IT"]
        countries = ["US", "GB", "DE", "FR", "CA", "JP", "AU"]

        for i in range(num_clean):
            base_name = f"{random.choice(clean_names)} {i+1} Corp"
            inc_days_ago = random.randint(365, 3650)
            suite.append({
                "vendor_id": f"SYN-CLEAN-{i+1:04d}",
                "name": base_name,
                "legal_name": f"{base_name} Inc.",
                "registration_number": f"{random.randint(10, 99)}-{random.randint(1000000, 9999999)}",
                "country": random.choice(countries),
                "annual_revenue_usd": float(random.randint(1000000, 50000000)),
                "employee_count": random.randint(20, 1000),
                "beneficial_owners": ["Jane Doe", "John Smith"],
                "incorporation_date": (datetime.utcnow() - timedelta(days=inc_days_ago)).isoformat(),
                "bank_account_number": f"US{random.randint(10, 99)}CHAS{random.randint(1000000000, 9999999999)}",
                "bank_change_recency_hours": float(random.randint(500, 20000)),
                "expected_label": 0,  # Legitimate
                "scenario_type": "CLEAN_ENTERPRISE",
            })

        # 2. Fraud & High-Risk Edge Cases
        fraud_scenarios = [
            ("SHELL_COMPANY", "Apex Shell Trading Ltd", "US", 15, 0, [], 10.0),
            ("SANCTION_COLLISION", "Rosneft Oil Regional Supply", "RU", 2000, 500, ["Oleg Volkov"], 5000.0),
            ("COLLUSIVE_ADDRESS", "Phantom Logistics LLC", "US", 25, 2, ["Colluding Officer"], 12.0),
            ("BANK_MODIFICATION_FRAUD", "Apex Solutions Intercept", "GB", 400, 15, ["Unknown Actor"], 18.0),
            ("INVALID_TAX_IDENTITY", "Ghost Enterprise Group", "US", 45, 1, [], 1500.0),
        ]

        for i in range(num_fraud):
            sc_type, name, country, age_days, employees, owners, bank_recency = fraud_scenarios[i % len(fraud_scenarios)]
            suite.append({
                "vendor_id": f"SYN-RISK-{i+1:04d}",
                "name": f"{name} #{i+1}",
                "legal_name": f"{name} #{i+1} Inc",
                "registration_number": "INVALID-TAX-0000" if sc_type == "INVALID_TAX_IDENTITY" else f"{random.randint(10, 99)}-{random.randint(1000000, 9999999)}",
                "country": country,
                "annual_revenue_usd": float(random.randint(50000, 500000)),
                "employee_count": employees,
                "beneficial_owners": owners,
                "incorporation_date": (datetime.utcnow() - timedelta(days=age_days)).isoformat(),
                "bank_account_number": f"US{random.randint(10, 99)}CHAS9999999999",  # shared bank collision
                "bank_change_recency_hours": bank_recency,
                "expected_label": 1,  # Risk / Fraud
                "scenario_type": sc_type,
            })

        random.shuffle(suite)
        return suite

    @classmethod
    def generate_clean_vendors(cls, num_samples: int = 50):
        """Generate DataFrame of clean vendors."""
        import pandas as pd
        suite = cls.generate_benchmark_suite(num_samples=num_samples, fraud_ratio=0.0)
        return pd.DataFrame(suite)

    @classmethod
    def generate_synthetic_batch(cls, num_samples: int = 50, fraud_ratio: float = 0.20):
        """Generate DataFrame with mixture of clean and fraud cases."""
        import pandas as pd
        suite = cls.generate_benchmark_suite(num_samples=num_samples, fraud_ratio=fraud_ratio)
        return pd.DataFrame(suite)


# Backward compatible alias
SyntheticDataGenerator = SyntheticVendorDataGenerator

