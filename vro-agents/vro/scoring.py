"""Deterministic scoring + tiering (plan §15.2). Pure functions; versioned; every score decomposes to factors (NFR-010).

GR-004: only this module produces scores/tiers. LLM-proposed numbers are never accepted.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import TierProposal, VendorIntake

BANDS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


@dataclass
class CheckResult:
    check_id: str
    weight: float
    coverage: float   # 0..1  how much of the requirement is evidenced (missing evidence = 0, never assumed OK)
    quality: float    # 0..1  opinion type, exceptions, recency, scope
    note: str = ""


class ScoringEngine:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.version = cfg["scoring_version"]

    # ------------------------------------------------------------------ inherent risk
    def _geo(self, intake: VendorIntake) -> tuple[float, str]:
        g = self.cfg["geo_risk"]
        places = [intake.country_iso2] + [p.strip().upper()[:2] for p in intake.data_access.storage_locations if p.strip()]
        vals = []
        for p in places:
            if p in g["high_risk"]:
                vals.append((g["high_risk_score"], f"{p} on high-risk country list"))
            elif p in g["low_risk"]:
                vals.append((g["low_risk"][p], f"{p} low-risk"))
            else:
                vals.append((g["default"], f"{p} not in country-risk table (default)"))
        return max(vals, key=lambda x: x[0])

    def _spend(self, spend: float | None) -> tuple[float, str]:
        if spend is None:
            return 0.5, "spend unknown (treated as mid materiality)"
        for band in self.cfg["financial_materiality"]:
            if band["max"] is None or spend < band["max"]:
                return band["value"], f"annual spend ${spend:,.0f}"
        return 1.0, "spend above all bands"

    def inherent(self, intake: VendorIntake) -> TierProposal:
        c, w, s = self.cfg, self.cfg["weights"], self.cfg["scales"]
        da = intake.data_access
        top_data = max(da.data_types, key=lambda d: s["data_sensitivity"][d])
        geo, geo_note = self._geo(intake)
        spend, spend_note = self._spend(intake.annual_spend_usd)
        fp = c["fourth_party"]
        fourth = min(fp["cap"], fp["per_subcontractor"] * len(intake.subcontractors))
        f = {
            "data_sensitivity": (s["data_sensitivity"][top_data], f"highest data class: {top_data}"),
            "data_volume": (s["data_volume"][da.volume], f"volume: {da.volume}"),
            "access_type": (s["access_type"][da.access_type], f"access: {da.access_type}"),
            "business_criticality": (s["business_criticality"][intake.criticality_hint], f"criticality: {intake.criticality_hint}"),
            "substitutability": (s["substitutability"][intake.substitutability], f"substitutability: {intake.substitutability}"),
            "customer_facing": (1.0 if intake.customer_facing else 0.0, "customer-facing / regulatory reporting impact" if intake.customer_facing else "not customer-facing"),
            "geo_risk": (geo, geo_note),
            "fourth_party": (fourth, f"{len(intake.subcontractors)} declared subcontractor(s)"),
            "financial_materiality": (spend, spend_note),
            "regulatory_class": (1.0 if intake.regulatory_critical else 0.0, "regulatory-critical service flag" if intake.regulatory_critical else "no regulatory-critical flag"),
        }
        factors, score = {}, 0.0
        for name, (val, note) in f.items():
            contrib = 100.0 * w[name] * val
            score += contrib
            factors[name] = {"value": round(val, 3), "weight": w[name], "contribution": round(contrib, 2), "reason": note}
        score = round(score, 2)
        t = c["tiers"]
        tier = 1 if score >= t["t1_min"] else 2 if score >= t["t2_min"] else 3 if score >= t["t3_min"] else 4
        floors: list[str] = []
        fl = c["floors"]
        if intake.regulatory_critical and tier > fl["regulatory_critical"]:
            floors.append("regulatory_critical"); tier = fl["regulatory_critical"]
        if ("customer_pii" in da.data_types and da.access_type in ("privileged", "network_connectivity")
                and tier > fl["pii_and_privileged"]):
            floors.append("pii_and_privileged"); tier = fl["pii_and_privileged"]
        if "payment_card" in da.data_types and tier > fl["payment_card"]:
            floors.append("payment_card"); tier = fl["payment_card"]
        top3 = sorted(factors.items(), key=lambda kv: -kv[1]["contribution"])[:3]
        rationale = (f"Inherent score {score}/100 -> T{tier}. Top drivers: "
                     + "; ".join(f"{k} ({v['reason']}, +{v['contribution']})" for k, v in top3)
                     + (f". Tier floor applied: {', '.join(floors)}." if floors else "."))
        return TierProposal(inherent_score=score, tier=tier, factors=factors, floors_applied=floors,
                            rationale=rationale, scoring_version=self.version)

    # ------------------------------------------------------------------ control effectiveness
    @staticmethod
    def domain_ce(checks: list[CheckResult]) -> float:
        tot = sum(c.weight for c in checks)
        if tot <= 0:
            return 0.0
        return round(sum(c.coverage * c.quality * c.weight for c in checks) / tot, 4)

    def control_effectiveness(self, by_domain: dict[str, list[CheckResult]]) -> dict:
        out = {}
        for d in self.cfg["control_domain_weights"]:
            checks = by_domain.get(d, [])
            out[d] = {"ce": self.domain_ce(checks),
                      "checks": [c.__dict__ for c in checks]}
        return out

    # ------------------------------------------------------------------ residual
    def band(self, residual: float) -> str:
        b = self.cfg["residual_bands"]
        return "LOW" if residual < b["low_max"] else "MEDIUM" if residual < b["medium_max"] else "HIGH" if residual < b["high_max"] else "CRITICAL"

    def residual(self, inherent_score: float, ce: dict, severities: list[str]) -> dict:
        om = self.cfg["control_domain_weights"]
        weighted_ce = round(sum(om[d] * ce[d]["ce"] for d in om), 4)
        r = round(inherent_score * (1 - weighted_ce), 2)
        band = self.band(r)
        capped = False
        if "CRITICAL" in severities and BANDS.index(band) < BANDS.index(self.cfg["critical_finding_min_band"]):
            band, capped = self.cfg["critical_finding_min_band"], True
        # Extension to plan 15.2 (policy-as-data, see ADR-0006): open HIGH findings put a floor under the band so strong
        # controls elsewhere cannot average away a serious gap.
        hf = self.cfg.get("high_finding_floor", {})
        n_high = sum(1 for sv in severities if sv == "HIGH")
        want = None
        if hf and n_high >= hf.get("many_count", 99):
            want = hf.get("many_band")
        elif hf and n_high >= 1:
            want = hf.get("one_band")
        if want and BANDS.index(band) < BANDS.index(want):
            band, capped = want, True
        return {"inherent_score": inherent_score, "weighted_control_effectiveness": weighted_ce, "residual_score": r,
                "band": band, "critical_cap_applied": capped}
