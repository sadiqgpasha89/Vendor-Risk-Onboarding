"""Evaluation Benchmark Datasets with Ground Truth Labels."""

from typing import List, Dict, Any


GOLDEN_BENCHMARK_CASES: List[Dict[str, Any]] = [
    {
        "id": "CASE-001-CLEAN-TECH",
        "vendor": {
            "name": "CloudSphere Technologies Inc",
            "legal_name": "CloudSphere Technologies Incorporated",
            "registration_number": "12-3456789",
            "country": "US",
            "industry": "Cloud Computing",
            "bank_account_age_days": 720,
            "bank_change_recency_hours": 8760,
            "annual_revenue": 25000000.0,
            "employee_count": 150,
            "bank_country": "US",
        },
        "expected": {
            "tier1_violations_count": 0,
            "sanctions_hits_count": 0,
            "risk_tier": "LOW",
            "decision": "AUTOMATED_APPROVAL",
            "hitl_required": False,
        },
    },
    {
        "id": "CASE-002-SANCTIONED-COLLISION",
        "vendor": {
            "name": "Rosoboron Defense Export",
            "legal_name": "Rosoboronexport State Corporation",
            "registration_number": "RU-7700112233",
            "country": "RU",
            "industry": "Defense",
            "bank_account_age_days": 1000,
            "bank_change_recency_hours": 5000,
            "annual_revenue": 100000000.0,
            "employee_count": 5000,
            "bank_country": "RU",
        },
        "expected": {
            "tier1_violations_count": 1,
            "sanctions_hits_count": 1,
            "risk_tier": "CRITICAL",
            "decision": "REJECT",
            "hitl_required": True,
        },
    },
    {
        "id": "CASE-003-SHELL-ACCOUNT-TAKEOVER",
        "vendor": {
            "name": "Swift Logistics Quick LLC",
            "legal_name": "Swift Logistics Quick LLC",
            "registration_number": "99-8877665",
            "country": "US",
            "industry": "Logistics",
            "bank_account_age_days": 2,  # Bank account modified < 72h
            "bank_change_recency_hours": 24,
            "annual_revenue": 50000.0,
            "employee_count": 1,
            "bank_country": "CY",
        },
        "expected": {
            "tier1_violations_count": 1,
            "risk_tier": "CRITICAL",
            "decision": "REJECT",
            "hitl_required": True,
        },
    },
    {
        "id": "CASE-004-MODERATE-STARTUP",
        "vendor": {
            "name": "Veritas Cybersecurity Ltd",
            "legal_name": "Veritas Cybersecurity Limited",
            "registration_number": "GB-88334411",
            "country": "GB",
            "industry": "Information Security",
            "bank_account_age_days": 180,
            "bank_change_recency_hours": 4320,
            "annual_revenue": 1200000.0,
            "employee_count": 12,
            "bank_country": "GB",
        },
        "expected": {
            "tier1_violations_count": 0,
            "sanctions_hits_count": 0,
            "risk_tier": "LOW",
            "decision": "AUTOMATED_APPROVAL",
            "hitl_required": False,
        },
    },
    {
        "id": "CASE-005-INVALID-TAX-IDENTITY",
        "vendor": {
            "name": "Shadow Peak Enterprises",
            "legal_name": "Shadow Peak Enterprises Corp",
            "registration_number": "INVALID-FORMAT-9999",
            "country": "US",
            "industry": "Procurement Services",
            "bank_account_age_days": 90,
            "bank_change_recency_hours": 2160,
            "annual_revenue": 300000.0,
            "employee_count": 2,
            "bank_country": "US",
        },
        "expected": {
            "tier1_violations_count": 1,
            "risk_tier": "HIGH",
            "decision": "REJECT",
            "hitl_required": True,
        },
    },
]


def load_evaluation_cases() -> List[Dict[str, Any]]:
    """Return benchmark evaluation test cases."""
    return GOLDEN_BENCHMARK_CASES
