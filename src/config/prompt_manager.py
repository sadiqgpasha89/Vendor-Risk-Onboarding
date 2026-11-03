"""Prompt Management System - Version control and organization of LLM prompts."""

import json
import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
import hashlib

logger = logging.getLogger(__name__)


@dataclass
class PromptVersion:
    """Single prompt version."""

    version: str
    name: str
    description: str
    category: str
    template: str
    variables: List[str]
    model: str
    temperature: float
    max_tokens: int
    tags: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    created_by: str = "system"
    notes: str = ""
    is_active: bool = True

    def get_hash(self) -> str:
        """Get content hash for version tracking."""
        content = f"{self.template}{self.variables}{self.model}{self.temperature}"
        return hashlib.md5(content.encode()).hexdigest()[:8]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class Prompt:
    """Prompt with version history."""

    name: str
    category: str
    description: str
    versions: List[PromptVersion] = field(default_factory=list)
    default_version: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    usage_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_active_version(self) -> Optional[PromptVersion]:
        """Get currently active version."""
        if self.default_version:
            for v in self.versions:
                if v.version == self.default_version:
                    return v

        # Return latest active version
        active_versions = [v for v in self.versions if v.is_active]
        if active_versions:
            return sorted(active_versions, key=lambda x: x.created_at, reverse=True)[0]

        return None

    def get_version(self, version_id: str) -> Optional[PromptVersion]:
        """Get specific version."""
        return next((v for v in self.versions if v.version == version_id), None)

    def add_version(self, version: PromptVersion) -> None:
        """Add a new version."""
        # Check if version already exists
        if any(v.version == version.version for v in self.versions):
            raise ValueError(f"Version {version.version} already exists")

        self.versions.append(version)
        logger.info(f"Added version {version.version} to prompt {self.name}")

    def render(self, variables: Dict[str, str], version_id: Optional[str] = None) -> str:
        """Render prompt with variables.

        Args:
            variables: Dictionary of variable values
            version_id: Specific version to use (defaults to active)

            Returns:
            Rendered prompt string
        """
        version = self.get_version(version_id) if version_id else self.get_active_version()

        if not version:
            raise ValueError(f"No prompt version found")

        template = version.template

        # Replace variables
        for var in version.variables:
            if var not in variables:
                logger.warning(f"Missing variable '{var}' in prompt rendering")
            else:
                template = template.replace(f"{{{{{var}}}}}", variables[var])

        self.usage_count += 1
        return template

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "versions": [v.to_dict() for v in self.versions],
            "default_version": self.default_version,
            "created_at": self.created_at,
            "usage_count": self.usage_count,
            "metadata": self.metadata,
        }


class PromptRegistry:
    """Registry for managing prompts."""

    def __init__(self, base_path: str = "prompts"):
        """Initialize prompt registry.

        Args:
            base_path: Base directory for prompt files
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.prompts: Dict[str, Prompt] = {}
        self._load_prompts()

    def _load_prompts(self) -> None:
        """Load prompts from disk."""
        for category_dir in self.base_path.iterdir():
            if not category_dir.is_dir():
                continue

            for prompt_file in category_dir.glob("*.json"):
                try:
                    with open(prompt_file) as f:
                        data = json.load(f)
                        prompt = self._deserialize_prompt(data)
                        self.prompts[prompt.name] = prompt
                        logger.info(f"Loaded prompt: {prompt.name}")
                except Exception as e:
                    logger.error(f"Error loading prompt {prompt_file}: {e}")

    def _deserialize_prompt(self, data: Dict[str, Any]) -> Prompt:
        """Deserialize prompt from dictionary."""
        versions = [
            PromptVersion(**v) for v in data.get("versions", [])
        ]

        prompt = Prompt(
            name=data["name"],
            category=data["category"],
            description=data["description"],
            versions=versions,
            default_version=data.get("default_version"),
            created_at=data.get("created_at", datetime.utcnow().isoformat()),
            usage_count=data.get("usage_count", 0),
            metadata=data.get("metadata", {}),
        )

        return prompt

    def register_prompt(self, prompt: Prompt) -> None:
        """Register a prompt in the registry.

        Args:
            prompt: Prompt object to register
        """
        self.prompts[prompt.name] = prompt
        self._save_prompt(prompt)
        logger.info(f"Registered prompt: {prompt.name}")

    def _save_prompt(self, prompt: Prompt) -> None:
        """Save prompt to disk."""
        category_path = self.base_path / prompt.category
        category_path.mkdir(parents=True, exist_ok=True)

        prompt_file = category_path / f"{prompt.name}.json"

        with open(prompt_file, "w") as f:
            json.dump(prompt.to_dict(), f, indent=2)

        logger.debug(f"Saved prompt to {prompt_file}")

    def get_prompt(self, name: str) -> Optional[Prompt]:
        """Get prompt by name."""
        return self.prompts.get(name)

    def render_prompt(
        self,
        prompt_name: str,
        variables: Dict[str, str],
        version_id: Optional[str] = None,
    ) -> str:
        """Render a prompt with variables.

        Args:
            prompt_name: Name of prompt
            variables: Variable values
            version_id: Optional version ID

            Returns:
            Rendered prompt string
        """
        prompt = self.get_prompt(prompt_name)
        if not prompt:
            raise ValueError(f"Prompt '{prompt_name}' not found")

        return prompt.render(variables, version_id)

    def add_version(
        self,
        prompt_name: str,
        version_id: str,
        template: str,
        variables: List[str],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        description: str = "",
        tags: Optional[List[str]] = None,
    ) -> None:
        """Add a new version to existing prompt.

        Args:
            prompt_name: Name of prompt
            version_id: Version identifier
            template: Prompt template with {{variable}} placeholders
            variables: List of variable names
            model: Target model
            temperature: Model temperature
            max_tokens: Max tokens for response
            description: Version description
            tags: Optional tags
        """
        prompt = self.get_prompt(prompt_name)
        if not prompt:
            raise ValueError(f"Prompt '{prompt_name}' not found")

        new_version = PromptVersion(
            version=version_id,
            name=prompt_name,
            description=description or prompt.description,
            category=prompt.category,
            template=template,
            variables=variables,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tags=tags or [],
        )

        prompt.add_version(new_version)
        self._save_prompt(prompt)

    def get_prompts_by_category(self, category: str) -> List[Prompt]:
        """Get all prompts in a category."""
        return [p for p in self.prompts.values() if p.category == category]

    def get_prompts_by_tags(self, tags: List[str]) -> List[Prompt]:
        """Get prompts matching tags."""
        matching = []
        for prompt in self.prompts.values():
            for version in prompt.versions:
                if any(tag in version.tags for tag in tags):
                    matching.append(prompt)
                    break

        return matching

    def get_statistics(self) -> Dict[str, Any]:
        """Get registry statistics."""
        total_prompts = len(self.prompts)
        total_versions = sum(len(p.versions) for p in self.prompts.values())
        total_usage = sum(p.usage_count for p in self.prompts.values())

        categories = {}
        for prompt in self.prompts.values():
            if prompt.category not in categories:
                categories[prompt.category] = {"count": 0, "usage": 0}
            categories[prompt.category]["count"] += 1
            categories[prompt.category]["usage"] += prompt.usage_count

        return {
            "total_prompts": total_prompts,
            "total_versions": total_versions,
            "total_usage": total_usage,
            "categories": categories,
            "avg_versions_per_prompt": total_versions / max(total_prompts, 1),
        }

    def export_prompts(self, path: str, category: Optional[str] = None) -> None:
        """Export prompts to external file.

        Args:
            path: Export file path
            category: Optional category filter
        """
        prompts_to_export = self.prompts.values()
        if category:
            prompts_to_export = [p for p in prompts_to_export if p.category == category]

        data = {
            "exported_at": datetime.utcnow().isoformat(),
            "count": len(prompts_to_export),
            "prompts": [p.to_dict() for p in prompts_to_export],
        }

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Exported {len(prompts_to_export)} prompts to {path}")

    def import_prompts(self, path: str) -> None:
        """Import prompts from external file.

        Args:
            path: Import file path
        """
        with open(path) as f:
            data = json.load(f)

        for prompt_data in data.get("prompts", []):
            prompt = self._deserialize_prompt(prompt_data)
            self.register_prompt(prompt)

        logger.info(f"Imported {len(data.get('prompts', []))} prompts")
