"""Policy engine: gates, SoD, legal transitions, per-tier plans, jurisdiction overlays (plan §3.4, §6.8).

All hard rules live here as code over policy-as-data (R1). Agents cannot reach this module's decisions.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .util import canonical_json, sha256_text

TRANSITIONS: dict[str, set[str]] = {
    "NEW": {"INTAKE_REVIEW"},
    "INTAKE_REVIEW": {"SCREENING", "ON_HOLD"},
    "SCREENING": {"HUMAN_SCREEN_REVIEW", "TIERING"},
    "HUMAN_SCREEN_REVIEW": {"TIERING", "REJECTED"},
    "TIERING": {"DUE_DILIGENCE"},
    "DUE_DILIGENCE": {"ASSESSMENT", "ON_HOLD"},
    "ASSESSMENT": {"VERIFICATION"},
    "VERIFICATION": {"HUMAN_REVIEW", "ASSESSMENT"},
    "HUMAN_REVIEW": {"CONTRACTING", "REJECTED", "ASSESSMENT"},   # ->ASSESSMENT = reviewer-requested rework (extension)
    "CONTRACTING": {"FINAL_APPROVAL"},
    "FINAL_APPROVAL": {"ONBOARDED", "REJECTED"},
    "ONBOARDED": {"MONITORING"},
    "MONITORING": {"ASSESSMENT", "OFFBOARDING"},
    "ON_HOLD": {"INTAKE_REVIEW", "DUE_DILIGENCE"},               # ->DUE_DILIGENCE = vendor docs arrived (extension)
    "OFFBOARDING": {"CLOSED"},
    "REJECTED": set(),
    "CLOSED": set(),
}
ALL_STATES = set(TRANSITIONS)
TERMINAL = {"REJECTED", "CLOSED"}
EMERGENCY_FROM = {"DUE_DILIGENCE", "ASSESSMENT", "VERIFICATION", "HUMAN_REVIEW", "CONTRACTING", "FINAL_APPROVAL"}


class PolicyError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class PolicyEngine:
    def __init__(self, policy_dir: str, pack: str = "default"):
        self.dir = Path(policy_dir)
        self.pack_name = pack
        self.reload()

    def reload(self, pack: str | None = None) -> None:
        if pack:
            self.pack_name = pack
        base = self.dir / "packs" / self.pack_name
        self.scoring = yaml.safe_load((base / "scoring.yaml").read_text())
        self.gates = yaml.safe_load((base / "gates.yaml").read_text())
        self.regions = {}
        for f in sorted((self.dir / "packs" / "regions").glob("*.yaml")):
            d = yaml.safe_load(f.read_text())
            self.regions[d["region"]] = d
        self.version = self.pack_name + "@" + sha256_text(canonical_json([self.scoring, self.gates, self.regions]))[:12]

    # ---- roles / gates -----------------------------------------------------
    def role_can(self, role: str, permission: str) -> bool:
        r = self.gates["roles"].get(role)
        return bool(r) and (permission in r["can"])

    def gate_name(self, gate: str, tier: int | None) -> str:
        return f"G4_T{tier}" if gate == "G4" and tier else gate

    def gate_roles(self, gate: str, tier: int | None = None) -> list[str]:
        return self.gates["gate_roles"].get(self.gate_name(gate, tier), [])

    def check_gate_actor(self, gate: str, tier: int | None, role: str) -> None:
        if role not in self.gate_roles(gate, tier):
            raise PolicyError("E_ROLE", f"role '{role}' may not decide gate {self.gate_name(gate, tier)}; "
                                         f"allowed: {self.gate_roles(gate, tier)}")

    def sla_hours(self, gate: str, tier: int | None = None) -> int:
        return int(self.gates["sla_hours"].get(self.gate_name(gate, tier), 48))

    # ---- transitions -------------------------------------------------------
    def check_transition(self, frm: str, to: str) -> None:
        if to not in ALL_STATES:
            raise PolicyError("E_STATE", f"unknown state {to}")
        if to not in TRANSITIONS.get(frm, set()):
            raise PolicyError("E_TRANSITION", f"illegal transition {frm} -> {to}")

    def check_screening_to_tiering(self, unresolved_matches: int) -> None:
        if unresolved_matches > 0:
            raise PolicyError("E_SANCTIONS_UNRESOLVED",
                              "SCREENING/HUMAN_SCREEN_REVIEW -> TIERING is forbidden while a potential sanctions match is unresolved")

    def check_sod(self, approver_id: str, requester_id: str, preparer_id: str | None) -> None:
        """GR-006: approver != requester != preparer."""
        if approver_id == requester_id:
            raise PolicyError("E_SOD", "segregation of duties: approver cannot be the requester")
        if preparer_id and approver_id == preparer_id:
            raise PolicyError("E_SOD", "segregation of duties: approver cannot be the analyst who prepared the review")

    def check_can_approve(self, open_critical: int) -> None:
        if open_critical > 0:
            raise PolicyError("E_CRITICAL_OPEN", f"{open_critical} CRITICAL finding(s) without remediation/exception block approval")

    def check_conditional_expiry(self, days: int) -> None:
        if days > self.gates["conditional_max_days"] or days < 1:
            raise PolicyError("E_CONDITIONAL_EXPIRY", f"conditional approval expiry must be 1..{self.gates['conditional_max_days']} days")

    # ---- plan for a case ---------------------------------------------------
    def plan(self, tier: int, jurisdictions: list[str]) -> dict:
        required = list(self.gates["evidence_matrix"].get(tier, []))
        clauses: list[str] = []
        refs: dict[str, str] = {}
        for j in jurisdictions:
            reg = self.regions.get(j)
            if not reg:
                continue
            for d in reg.get("additional_evidence", {}).get(tier, []):
                if d not in required:
                    required.append(d)
            for c in reg.get("required_clauses", []):
                if c not in clauses:
                    clauses.append(c)
            for k, v in reg.get("regulation_refs", {}).items():
                refs[f"{j}:{k}"] = v
        return {
            "tier": tier,
            "required_docs": required,
            "required_clauses": clauses,
            "specialists": self.gates["specialists_by_tier"].get(tier, ["A5"]),
            "requires_g2": tier in self.gates["requires_g2_tiers"],
            "approver_gate": f"G4_T{tier}",
            "regulation_refs": refs,
            "policy_version": self.version,
        }

    def regulation_ref(self, jurisdictions: list[str], key: str) -> list[str]:
        out = []
        for j in jurisdictions:
            r = self.regions.get(j, {}).get("regulation_refs", {}).get(key)
            if r:
                out.append(r)
        return out

    def max_age_days(self, predicate: str) -> int:
        m = self.gates["max_age_days"]
        for k, v in m.items():
            if k != "default" and predicate.startswith(k):
                return int(v)
        return int(m["default"])
