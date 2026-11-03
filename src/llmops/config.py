"""LLMOps configuration and model registry."""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from enum import Enum
import json
import yaml
from datetime import datetime


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    HUGGINGFACE = "huggingface"


class EvaluationMetric(str, Enum):
    """Evaluation metrics for LLMOps."""

    CORRECTNESS = "correctness"
    FAITHFULNESS = "faithfulness"
    RELEVANCE = "relevance"
    COHERENCE = "coherence"
    CONSISTENCY = "consistency"
    LATENCY = "latency"
    COST = "cost"


@dataclass
class ModelConfig:
    """LLM Model configuration."""

    provider: LLMProvider
    model_name: str
    version: str
    temperature: float = 0.3
    max_tokens: int = 4096
    top_p: float = 0.95
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    system_prompt: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "provider": self.provider.value,
            "model_name": self.model_name,
            "version": self.version,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "system_prompt": self.system_prompt,
            "tags": self.tags,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class PromptConfig:
    """Prompt template configuration."""

    name: str
    version: str
    template: str
    description: str
    variables: list = field(default_factory=list)
    tags: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "version": self.version,
            "template": self.template,
            "description": self.description,
            "variables": self.variables,
            "tags": self.tags,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class EvaluationConfig:
    """Evaluation framework configuration."""

    metric: EvaluationMetric
    threshold: float
    weight: float = 1.0
    enabled: bool = True
    sample_size: Optional[int] = None
    dataset_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "metric": self.metric.value,
            "threshold": self.threshold,
            "weight": self.weight,
            "enabled": self.enabled,
            "sample_size": self.sample_size,
            "dataset_path": self.dataset_path,
        }


@dataclass
class MonitoringConfig:
    """Monitoring and observability configuration."""

    enabled: bool = True
    log_level: str = "INFO"
    trace_sample_rate: float = 1.0
    metrics_enabled: bool = True
    jaeger_enabled: bool = True
    sentry_enabled: bool = False
    langsmith_enabled: bool = True
    wandb_enabled: bool = True
    mlflow_enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "enabled": self.enabled,
            "log_level": self.log_level,
            "trace_sample_rate": self.trace_sample_rate,
            "metrics_enabled": self.metrics_enabled,
            "jaeger_enabled": self.jaeger_enabled,
            "sentry_enabled": self.sentry_enabled,
            "langsmith_enabled": self.langsmith_enabled,
            "wandb_enabled": self.wandb_enabled,
            "mlflow_enabled": self.mlflow_enabled,
        }


class LLMOpsConfig:
    """Central LLMOps configuration manager."""

    def __init__(self):
        """Initialize LLMOps configuration."""
        self.models: Dict[str, ModelConfig] = {}
        self.prompts: Dict[str, PromptConfig] = {}
        self.evaluations: Dict[str, EvaluationConfig] = {}
        self.monitoring = MonitoringConfig()

    def register_model(self, config: ModelConfig) -> None:
        """Register a model configuration."""
        key = f"{config.provider.value}/{config.model_name}/{config.version}"
        self.models[key] = config

    def get_model(self, provider: LLMProvider, model_name: str, version: str = "latest") -> Optional[ModelConfig]:
        """Get model configuration."""
        key = f"{provider.value}/{model_name}/{version}"
        return self.models.get(key)

    def register_prompt(self, config: PromptConfig) -> None:
        """Register a prompt configuration."""
        key = f"{config.name}/{config.version}"
        self.prompts[key] = config

    def get_prompt(self, name: str, version: str = "latest") -> Optional[PromptConfig]:
        """Get prompt configuration."""
        key = f"{name}/{version}"
        return self.prompts.get(key)

    def register_evaluation(self, name: str, config: EvaluationConfig) -> None:
        """Register evaluation configuration."""
        self.evaluations[name] = config

    def get_evaluation(self, name: str) -> Optional[EvaluationConfig]:
        """Get evaluation configuration."""
        return self.evaluations.get(name)

    def load_from_yaml(self, yaml_path: str) -> None:
        """Load configuration from YAML file."""
        with open(yaml_path, "r") as f:
            config = yaml.safe_load(f)

        # Load models
        if "models" in config:
            for model_config in config["models"]:
                self.register_model(ModelConfig(**model_config))

        # Load prompts
        if "prompts" in config:
            for prompt_config in config["prompts"]:
                self.register_prompt(PromptConfig(**prompt_config))

        # Load evaluations
        if "evaluations" in config:
            for eval_name, eval_config in config["evaluations"].items():
                self.register_evaluation(eval_name, EvaluationConfig(**eval_config))

        # Load monitoring
        if "monitoring" in config:
            self.monitoring = MonitoringConfig(**config["monitoring"])

    def to_dict(self) -> Dict[str, Any]:
        """Export configuration as dictionary."""
        return {
            "models": {k: v.to_dict() for k, v in self.models.items()},
            "prompts": {k: v.to_dict() for k, v in self.prompts.items()},
            "evaluations": {k: v.to_dict() for k, v in self.evaluations.items()},
            "monitoring": self.monitoring.to_dict(),
        }

    def to_json(self, indent: int = 2) -> str:
        """Export configuration as JSON."""
        return json.dumps(self.to_dict(), indent=indent, default=str)


# Global LLMOps configuration instance
llmops_config = LLMOpsConfig()
