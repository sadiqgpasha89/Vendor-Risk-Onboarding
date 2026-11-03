"""Tier 1 Deterministic Rules Engine: Sub-millisecond policy and statutory boundary enforcement."""

import logging
from typing import List, Dict, Any, Optional
from src.schemas.vendor import VendorProfile
from src.schemas.assessment import Tier1RuleViolation
from src.data_engineering.watchlist_pipeline import WatchlistPipeline, SanctionScreenResult
from src.utils.validators import validate_tax_id

logger = logging.getLogger(__name__)

HARD_SANCTIONED_COUNTRIES = {"KP", "IR", "SY", "CU", "RU"}


class Tier1RuleEngine:
    """Sub-millisecond deterministic statutory policy engine."""

    def __init__(self, watchlist_pipeline: Optional[WatchlistPipeline] = None):
        self.watchlist = watchlist_pipeline or WatchlistPipeline()

    def evaluate_rules(
        self,
        vendor: Any,
        feature_vector: Dict[str, Any],
    ) -> List[Tier1RuleViolation]:
        """Execute all deterministic policy checks against a vendor."""
        violations: List[Tier1RuleViolation] = []

        if isinstance(vendor, dict):
            vendor = VendorProfile(
                id=vendor.get("id") or vendor.get("vendor_id") or "VEND-TEMP",
                name=vendor.get("name", ""),
                legal_name=vendor.get("legal_name", vendor.get("name", "")),
                registration_number=vendor.get("registration_number") or vendor.get("tax_id", ""),
                country=vendor.get("country", "US"),
                annual_revenue_usd=float(vendor.get("annual_revenue") or vendor.get("annual_revenue_usd") or 0.0),
                employee_count=int(vendor.get("employee_count") or 0),
                beneficial_owners=vendor.get("beneficial_owners") or [],
                bank_account_number=vendor.get("bank_account_number") or "",
            )

        # Rule 1: Sanctions Watchlist Screen
        sanction_res: SanctionScreenResult = self.watchlist.screen_entity(
            name=vendor.legal_name or vendor.name,
            tax_id=vendor.registration_number,
            country=vendor.country,
        )

        if sanction_res.is_exact_block:
            top_match = sanction_res.matches[0] if sanction_res.matches else None
            violations.append(
                Tier1RuleViolation(
                    rule_id="RULE-RBS-001",
                    rule_name="SANCTIONED_ENTITY_MATCH",
                    severity="HARD_BLOCK",
                    description=f"Exact match on official sanctions list ({top_match.list_name if top_match else 'SANCTIONS'}). Immediate statutory block required.",
                    evidence={
                        "highest_score": sanction_res.highest_match_score,
                        "matches": [m.__dict__ for m in sanction_res.matches],
                    },
                )
            )
        elif sanction_res.highest_match_score >= 0.85:
            violations.append(
                Tier1RuleViolation(
                    rule_id="RULE-RBS-002",
                    rule_name="POTENTIAL_SANCTION_MATCH",
                    severity="CRITICAL_HOLD",
                    description=f"High-confidence fuzzy match on sanctions list (score: {sanction_res.highest_match_score:.2f}).",
                    evidence={"highest_score": sanction_res.highest_match_score},
                )
            )

        # Rule 2: Country Embargo / Hard-Sanctioned Jurisdiction
        if vendor.country.upper() in HARD_SANCTIONED_COUNTRIES:
            violations.append(
                Tier1RuleViolation(
                    rule_id="RULE-RBS-003",
                    rule_name="EMBARGOED_JURISDICTION",
                    severity="HARD_BLOCK",
                    description=f"Vendor is incorporated in embargoed/sanctioned jurisdiction '{vendor.country}'.",
                    evidence={"country": vendor.country},
                )
            )

        # Rule 3: Mid-Cycle Bank Modification within 72 Hours
        if feature_vector.get("bank_change_within_72h") == 1.0:
            recency = feature_vector.get("bank_change_recency_hours", 0.0)
            violations.append(
                Tier1RuleViolation(
                    rule_id="RULE-RBS-004",
                    rule_name="RECENT_BANK_MODIFICATION",
                    severity="CRITICAL_HOLD",
                    description=f"Settlement banking details modified within 72 hours of onboarding ({recency:.1f}h ago). Fraud prevention freeze applied.",
                    evidence={"recency_hours": recency},
                )
            )

        # Rule 4: Invalid Tax Identification Number
        is_tax_valid, tax_msg = validate_tax_id(vendor.registration_number, country_code=vendor.country)
        if not is_tax_valid:
            violations.append(
                Tier1RuleViolation(
                    rule_id="RULE-RBS-005",
                    rule_name="INVALID_TAX_IDENTIFIER",
                    severity="CRITICAL_HOLD",
                    description=f"Invalid corporate registration/tax identifier: {tax_msg}",
                    evidence={"tax_id": vendor.registration_number, "reason": tax_msg},
                )
            )

        # Rule 5: Cross-Vendor Shared Bank Account Collision
        if feature_vector.get("shared_bank_account_cross_vendor") == 1.0:
            violations.append(
                Tier1RuleViolation(
                    rule_id="RULE-RBS-006",
                    rule_name="SHARED_BANK_ACCOUNT_COLLISION",
                    severity="CRITICAL_HOLD",
                    description="The designated bank account is already registered to another active corporate vendor. Potential shell/cartel collusion.",
                    evidence={"bank_account": vendor.bank_account_number},
                )
            )

        return violations
