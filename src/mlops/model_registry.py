"""MLOps Model Registry: Versioning, Metadata, Artifact Storage, and Stage Transitions."""

import os
import json
import logging
from enum import Enum
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime

logger = logging.getLogger(__name__)


class ModelStage(str, Enum):
    DRAFT = "DRAFT"
    STAGING = "STAGING"
    PRODUCTION = "PRODUCTION"
    ARCHIVED = "ARCHIVED"


@dataclass
class ModelVersionMetadata:
    model_name: str
    version: str
    stage: ModelStage
    algorithm: str
    feature_names: List[str]
    hyperparameters: Dict[str, Any]
    metrics: Dict[str, float]  # auc_pr, brier_score, precision_at_k, f1
    artifact_path: str
    author: str = "mlops_pipeline"
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    stage_updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class ModelRegistry:
    """Unified Model Registry supporting Open Stack (local/MLflow) and GCP (Vertex AI)."""

    def __init__(self, registry_dir: str = "/tmp/vendor_risk_model_registry"):
        self.registry_dir = registry_dir
        os.makedirs(self.registry_dir, exist_ok=True)
        self._models: Dict[str, Dict[str, ModelVersionMetadata]] = {}
        self._load_from_disk()

    def _get_model_file(self) -> str:
        return os.path.join(self.registry_dir, "model_registry.json")

    def _load_from_disk(self):
        filepath = self._get_model_file()
        if os.path.exists(filepath):
            try:
                with open(filepath, "r") as f:
                    data = json.load(f)
                    for model_name, versions in data.items():
                        self._models[model_name] = {}
                        for ver, meta in versions.items():
                            meta["stage"] = ModelStage(meta["stage"])
                            self._models[model_name][ver] = ModelVersionMetadata(**meta)
            except Exception as e:
                logger.warning(f"Could not load model registry from disk: {e}")

    def _save_to_disk(self):
        filepath = self._get_model_file()
        serializable = {}
        for m_name, v_dict in self._models.items():
            serializable[m_name] = {ver: asdict(meta) for ver, meta in v_dict.items()}
        with open(filepath, "w") as f:
            json.dump(serializable, f, indent=2)

    def register_model_version(
        self,
        model_name: str,
        version: str,
        algorithm: str,
        feature_names: List[str],
        hyperparameters: Dict[str, Any],
        metrics: Dict[str, float],
        artifact_path: str,
        description: str = "",
    ) -> ModelVersionMetadata:
        """Register a new candidate model version in DRAFT stage."""
        if model_name not in self._models:
            self._models[model_name] = {}

        metadata = ModelVersionMetadata(
            model_name=model_name,
            version=version,
            stage=ModelStage.DRAFT,
            algorithm=algorithm,
            feature_names=feature_names,
            hyperparameters=hyperparameters,
            metrics=metrics,
            artifact_path=artifact_path,
            description=description,
        )

        self._models[model_name][version] = metadata
        self._save_to_disk()
        logger.info(f"Registered model {model_name}:{version} in stage DRAFT")
        return metadata

    def register_model(
        self,
        model_name: str,
        version: str,
        algorithm: str = "lightgbm_gbdt",
        model_type: Optional[str] = None,
        feature_names: Optional[List[str]] = None,
        hyperparameters: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, float]] = None,
        artifact_path: str = "/tmp/model.pkl",
        description: str = "",
    ) -> ModelVersionMetadata:
        """Convenience method to register model with optional defaults."""
        return self.register_model_version(
            model_name=model_name,
            version=version,
            algorithm=model_type or algorithm,
            feature_names=feature_names or [],
            hyperparameters=hyperparameters or {},
            metrics=metrics or {},
            artifact_path=artifact_path,
            description=description,
        )

    def transition_stage(
        self,
        model_name: str,
        version: str,
        target_stage: ModelStage,
        archive_existing_production: bool = True,
    ) -> ModelVersionMetadata:
        """Transition a model version between lifecycle stages (e.g. STAGING -> PRODUCTION)."""
        if model_name not in self._models or version not in self._models[model_name]:
            raise KeyError(f"Model {model_name}:{version} not found in registry")

        # If promoting to PRODUCTION, automatically archive current PRODUCTION version
        if target_stage == ModelStage.PRODUCTION and archive_existing_production:
            for ver, meta in self._models[model_name].items():
                if meta.stage == ModelStage.PRODUCTION and ver != version:
                    meta.stage = ModelStage.ARCHIVED
                    meta.stage_updated_at = datetime.utcnow().isoformat()
                    logger.info(f"Archived previous production version {model_name}:{ver}")

        current = self._models[model_name][version]
        current.stage = target_stage
        current.stage_updated_at = datetime.utcnow().isoformat()
        self._save_to_disk()
        logger.info(f"Transitioned model {model_name}:{version} to stage {target_stage.value}")
        return current

    def get_production_model(self, model_name: str) -> Optional[ModelVersionMetadata]:
        """Retrieve active production model version metadata."""
        if model_name not in self._models:
            return None
        for meta in self._models[model_name].values():
            if meta.stage == ModelStage.PRODUCTION:
                return meta
        return None

    def list_models(self) -> Dict[str, List[Dict[str, Any]]]:
        """List all models and their versions."""
        result = {}
        for m_name, v_dict in self._models.items():
            result[m_name] = [asdict(meta) for meta in v_dict.values()]
        return result
