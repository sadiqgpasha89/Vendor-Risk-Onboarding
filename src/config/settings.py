"""Core application settings and configuration."""

from typing import Optional
from pydantic_settings import BaseSettings


class LLMSettings(BaseSettings):
    """LLM configuration."""

    provider: str = "openai"  # openai, azure, anthropic, ollama
    model: str = "gpt-4"
    temperature: float = 0.3
    max_tokens: int = 4096
    top_p: float = 0.95
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0

    openai_api_key: Optional[str] = None
    openai_org_id: Optional[str] = None
    azure_openai_api_key: Optional[str] = None
    azure_openai_endpoint: Optional[str] = None
    azure_openai_deployment: str = "vendor-risk"
    anthropic_api_key: Optional[str] = None

    google_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.0-flash"
    ollama_base_url: str = "http://localhost:11434"

    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536

    class Config:
        env_prefix = "LLM_"
        env_file = ".env"


class DatabaseSettings(BaseSettings):
    """Database configuration."""

    url: str = "postgresql://user:password@localhost:5432/vendor_risk"
    pool_size: int = 20
    max_overflow: int = 40
    pool_timeout: int = 30
    echo: bool = False
    ssl_mode: str = "prefer"

    class Config:
        env_prefix = "DATABASE_"
        env_file = ".env"


class RedisSettings(BaseSettings):
    """Redis configuration."""

    url: str = "redis://localhost:6379/0"
    cache_ttl: int = 3600
    socket_connect_timeout: int = 5
    socket_timeout: int = 5

    class Config:
        env_prefix = "REDIS_"
        env_file = ".env"


class CelerySettings(BaseSettings):
    """Celery configuration."""

    broker_url: str = "redis://localhost:6379/1"
    result_backend: str = "redis://localhost:6379/2"
    worker_concurrency: int = 4
    task_time_limit: int = 300
    task_soft_time_limit: int = 250

    class Config:
        env_prefix = "CELERY_"
        env_file = ".env"


class LLMOpsSettings(BaseSettings):
    """LLMOps and monitoring configuration."""

    langsmith_api_key: Optional[str] = None
    langsmith_project: str = "vendor-risk-onboarding"
    wandb_api_key: Optional[str] = None
    wandb_project: str = "vendor-risk-onboarding"
    mlflow_tracking_uri: str = "http://localhost:5000"
    mlflow_experiment_name: str = "vendor-risk-experiments"
    jaeger_agent_host: str = "localhost"
    jaeger_agent_port: int = 6831
    opentelemetry_enabled: bool = True
    sentry_dsn: Optional[str] = None

    class Config:
        env_prefix = "LANGSMITH_|WANDB_|MLFLOW_|JAEGER_|OPENTELEMETRY_|SENTRY_"
        env_file = ".env"


class AuthSettings(BaseSettings):
    """Authentication configuration."""

    secret_key: str = "your-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24
    jwt_refresh_expiration_days: int = 7

    class Config:
        env_prefix = "JWT_|SECRET_"
        env_file = ".env"


class APISettings(BaseSettings):
    """API configuration."""

    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4
    cors_origins: list = ["http://localhost:3000"]
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 100
    rate_limit_period: int = 60

    class Config:
        env_prefix = "API_|CORS_|RATE_LIMIT_"
        env_file = ".env"


class GCPSettings(BaseSettings):
    """Google Cloud Platform specific settings."""

    project_id: Optional[str] = None
    region: str = "us-central1"
    gcs_bucket: str = "vendor-risk-documents"
    pubsub_topic: str = "vendor-onboarding-events"
    pubsub_subscription: str = "vendor-onboarding-sub"
    bigquery_dataset: str = "vendor_risk_analytics"
    vertex_ai_location: str = "us-central1"
    vertex_ai_endpoint: Optional[str] = None
    document_ai_processor_id: Optional[str] = None

    class Config:
        env_prefix = "GCP_"
        env_file = ".env"


class Settings(BaseSettings):
    """Main application settings."""

    app_name: str = "Vendor Risk Onboarding"
    app_env: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # Cloud stack strategy: "open_stack" (OSS/Local) or "gcp" (Google Cloud)
    cloud_provider: str = "open_stack"

    # Sub-settings
    llm: LLMSettings = LLMSettings()
    database: DatabaseSettings = DatabaseSettings()
    redis: RedisSettings = RedisSettings()
    celery: CelerySettings = CelerySettings()
    llmops: LLMOpsSettings = LLMOpsSettings()
    auth: AuthSettings = AuthSettings()
    api: APISettings = APISettings()
    gcp: GCPSettings = GCPSettings()

    # Latency & Throughput optimizations
    batch_size: int = 50
    max_parallel_agents: int = 5
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_time_seconds: int = 30
    request_timeout_seconds: int = 30

    # File storage
    file_storage_path: str = "./data/uploads"
    file_storage_type: str = "local"  # local | s3 | gcs | azure
    max_document_size_mb: int = 50

    # Evaluation
    evaluation_enabled: bool = True
    evaluation_sample_size: int = 100
    evaluation_threshold: float = 0.8

    # Compliance
    audit_log_enabled: bool = True
    data_retention_days: int = 2555
    pii_masking_enabled: bool = True

    class Config:
        env_file = ".env"
        case_sensitive = False

    @property
    def database_url(self) -> str:
        """Get database URL."""
        return self.database.url


# Global settings instance
settings = Settings()
