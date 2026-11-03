"""Centralized Prompt Registry with Semantic Versioning, Variable Validation, and Rollback."""

import os
import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
from langchain_core.prompts import PromptTemplate

logger = logging.getLogger(__name__)


@dataclass
class PromptVersion:
    name: str
    version: str  # SemVer: "1.0.0"
    template: str
    input_variables: List[str]
    description: str = ""
    author: str = "system"
    tags: List[str] = field(default_factory=list)
    is_active: bool = False
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class PromptRegistry:
    """Enterprise Prompt Registry supporting version control, parameter enforcement, and rollback."""

    def __init__(self, storage_path: str = "/tmp/vendor_risk_prompt_registry.json"):
        self.storage_path = storage_path
        self._registry: Dict[str, Dict[str, PromptVersion]] = {}
        self._active_versions: Dict[str, str] = {}
        self._load_from_disk()
        self._register_default_prompts()

    def _load_from_disk(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r") as f:
                    data = json.load(f)
                    for name, versions in data.get("prompts", {}).items():
                        self._registry[name] = {}
                        for ver, p_data in versions.items():
                            self._registry[name][ver] = PromptVersion(**p_data)
                    self._active_versions = data.get("active", {})
            except Exception as e:
                logger.warning(f"Failed to load prompt registry: {e}")

    def _save_to_disk(self):
        try:
            data = {
                "prompts": {
                    name: {ver: asdict(p) for ver, p in v_dict.items()}
                    for name, v_dict in self._registry.items()
                },
                "active": self._active_versions,
            }
            with open(self.storage_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save prompt registry: {e}")

    def register_prompt(
        self,
        name: str,
        version: str,
        template: str,
        input_variables: List[str],
        description: str = "",
        set_active: bool = True,
    ) -> PromptVersion:
        """Register a new version of a prompt template."""
        if name not in self._registry:
            self._registry[name] = {}

        pv = PromptVersion(
            name=name,
            version=version,
            template=template,
            input_variables=input_variables,
            description=description,
            is_active=set_active,
        )

        self._registry[name][version] = pv

        if set_active:
            for v_name, v_obj in self._registry[name].items():
                v_obj.is_active = (v_name == version)
            self._active_versions[name] = version

        self._save_to_disk()
        logger.info(f"Registered prompt '{name}' v{version} (active={set_active})")
        return pv

    def get_prompt(self, name: str, version: Optional[str] = None) -> PromptTemplate:
        """Retrieve a PromptTemplate for the specified or active version."""
        if name not in self._registry:
            raise KeyError(f"Prompt '{name}' not registered")

        if version is None:
            version = self._active_versions.get(name)
            if not version or version not in self._registry[name]:
                # Pick latest version
                version = list(self._registry[name].keys())[-1]

        pv = self._registry[name][version]
        return PromptTemplate(
            input_variables=pv.input_variables,
            template=pv.template,
        )

    def format_prompt(self, name: str, version: Optional[str] = None, **kwargs) -> str:
        """Format a prompt ensuring all required input variables are supplied."""
        tmpl = self.get_prompt(name, version)
        # Validate variables
        missing = set(tmpl.input_variables) - set(kwargs.keys())
        if missing:
            raise ValueError(f"Missing required prompt variables for '{name}': {missing}")
        return tmpl.format(**kwargs)

    def rollback(self, name: str, target_version: str) -> PromptVersion:
        """Rollback active prompt version to an earlier release."""
        if name not in self._registry or target_version not in self._registry[name]:
            raise KeyError(f"Cannot rollback: version '{target_version}' not found for prompt '{name}'")

        for v_name, v_obj in self._registry[name].items():
            v_obj.is_active = (v_name == target_version)

        self._active_versions[name] = target_version
        self._save_to_disk()
        logger.info(f"Rolled back prompt '{name}' to v{target_version}")
        return self._registry[name][target_version]

    def list_templates(self) -> Dict[str, Any]:
        """List all prompt templates, versions, and active statuses."""
        return {
            name: {
                "active_version": self._active_versions.get(name),
                "versions": [asdict(v) for v in v_dict.values()],
            }
            for name, v_dict in self._registry.items()
        }

    def _register_default_prompts(self):
        """Seed initial prompt templates if empty."""
        if "kyc_validation" not in self._registry:
            self.register_prompt(
                name="kyc_validation",
                version="1.0.0",
                template="""Perform comprehensive KYC and sanctions validation for the following vendor:
Legal Name: {legal_name}
Registration / Tax ID: {registration_number}
Country: {country}
Sanction Screening Results: {sanctions_results}

Analyze compliance with OFAC, PEP registers, and statutory registries. Output structured JSON with verification status, risk flags, confidence score, and recommendations.""",
                input_variables=["legal_name", "registration_number", "country", "sanctions_results"],
                description="KYC and sanctions validation prompt",
            )

        if "compliance_check" not in self._registry:
            self.register_prompt(
                name="compliance_check",
                version="1.0.0",
                template="""Evaluate regulatory compliance for vendor:
Vendor: {vendor_name}
Country: {country}
Industry: {industry}
Extracted Documents: {documents_summary}

Verify compliance with SOX Section 404, AML/CFT mandates, GDPR, and ISO standards. Output structured JSON with compliance status, missing certifications, and regulatory risks.""",
                input_variables=["vendor_name", "country", "industry", "documents_summary"],
                description="Regulatory compliance evaluation prompt",
            )

        if "risk_synthesis" not in self._registry:
            self.register_prompt(
                name="risk_synthesis",
                version="1.0.0",
                template="""Synthesize all vendor risk findings into an audit-ready executive dossier:
Vendor ID: {vendor_id}
Tier 1 Rule Violations: {tier1_violations}
Tier 2 ML Anomaly & Risk Score: {tier2_ml_summary}
KYC Findings: {kyc_findings}
Compliance Findings: {compliance_findings}

Create a professional, evidence-backed evaluation with dimension scores (0-100), key red flags, remediation action items, and final approval/rejection recommendation.""",
                input_variables=["vendor_id", "tier1_violations", "tier2_ml_summary", "kyc_findings", "compliance_findings"],
                description="Comprehensive risk report synthesis prompt",
            )


# Global prompt registry instance
prompt_registry = PromptRegistry()
