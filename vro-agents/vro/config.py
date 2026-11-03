"""Runtime settings, read from environment (see .env.example). No secrets in code."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader (KEY=VALUE, '#' comments, optional quotes). Real environment variables always win. No dependency needed."""
    p = path or ROOT / ".env"
    if not p.is_file():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)


load_dotenv()


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    app_env: str = field(default_factory=lambda: os.environ.get("APP_ENV", "local"))
    db_path: str = field(default_factory=lambda: os.environ.get("VRO_DB_PATH", str(ROOT / "data" / "vro.db")))
    database_url: str = field(default_factory=lambda: os.environ.get("VRO_DATABASE_URL", ""))          # set => PostgreSQL, else SQLite
    database_url_admin: str = field(default_factory=lambda: os.environ.get("VRO_DATABASE_URL_ADMIN", ""))   # owner/system role: migrations, audit verification
    pg_rls: bool = field(default_factory=lambda: os.environ.get("VRO_PG_RLS", "0") == "1")
    pg_schema: str = field(default_factory=lambda: os.environ.get("VRO_PG_SCHEMA", ""))
    pg_pool_max: int = field(default_factory=lambda: int(_f("VRO_PG_POOL_MAX", 10)))
    # Embeddings for retrieval. "hashing" = offline stand-in. Others: ollama | google | openai (see vro/embeddings.py).
    embed_provider: str = field(default_factory=lambda: os.environ.get("EMBED_PROVIDER", "hashing"))
    embed_model: str = field(default_factory=lambda: os.environ.get("EMBED_MODEL", ""))
    embed_dim: int = field(default_factory=lambda: int(_f("VRO_EMBED_DIM", 512)))
    embed_base_url: str = field(default_factory=lambda: os.environ.get("EMBED_BASE_URL", ""))
    embed_api_key: str = field(default_factory=lambda: os.environ.get("EMBED_API_KEY", ""))
    pdf_ocr: bool = field(default_factory=lambda: os.environ.get("PDF_OCR", "1") == "1")
    ocr_langs: str = field(default_factory=lambda: os.environ.get("OCR_LANGS", "eng"))             # tesseract codes, e.g. eng+deu
    pdf_ocr_dpi: int = field(default_factory=lambda: int(_f("PDF_OCR_DPI", 200)))
    pdf_ocr_max_pages: int = field(default_factory=lambda: int(_f("PDF_OCR_MAX_PAGES", 60)))
    pdf_timeout_s: float = field(default_factory=lambda: _f("PDF_PARSE_TIMEOUT_S", 300))
    pdf_mem_mb: int = field(default_factory=lambda: int(_f("PDF_MEM_MB", 2048)))
    oidc_issuer: str = field(default_factory=lambda: os.environ.get("OIDC_ISSUER", ""))
    oidc_audience: str = field(default_factory=lambda: os.environ.get("OIDC_AUDIENCE", ""))
    oidc_jwks_url: str = field(default_factory=lambda: os.environ.get("OIDC_JWKS_URL", ""))
    oidc_role_claim: str = field(default_factory=lambda: os.environ.get("OIDC_ROLE_CLAIM", "roles"))
    oidc_tenant_claim: str = field(default_factory=lambda: os.environ.get("OIDC_TENANT_CLAIM", "tenant_id"))
    oidc_role_map: str = field(default_factory=lambda: os.environ.get("OIDC_ROLE_MAP", ""))     # JSON: {"idp-role": "internal-role"}
    rate_limit_rpm: int = field(default_factory=lambda: int(_f("RATE_LIMIT_RPM", 240)))         # reads, per principal
    rate_limit_write_rpm: int = field(default_factory=lambda: int(_f("RATE_LIMIT_WRITE_RPM", 60)))
    rate_limit_upload_rpm: int = field(default_factory=lambda: int(_f("RATE_LIMIT_UPLOAD_RPM", 20)))
    rate_limit_auth_fail_rpm: int = field(default_factory=lambda: int(_f("RATE_LIMIT_AUTH_FAIL_RPM", 20)))   # per client IP
    redis_url: str = field(default_factory=lambda: os.environ.get("REDIS_URL", ""))
    trusted_proxies: int = field(default_factory=lambda: int(_f("TRUSTED_PROXY_COUNT", 0)))     # hops of X-Forwarded-For to trust
    allowed_hosts: str = field(default_factory=lambda: os.environ.get("ALLOWED_HOSTS", ""))     # comma-separated Host allow-list
    api_threads: int = field(default_factory=lambda: int(_f("API_THREADS", 32)))
    job_workers: int = field(default_factory=lambda: int(_f("JOB_WORKERS", 4)))
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))
    policy_dir: str = field(default_factory=lambda: os.environ.get("VRO_POLICY_DIR", str(ROOT / "policy")))
    policy_pack: str = field(default_factory=lambda: os.environ.get("VRO_POLICY_PACK", "default"))
    # LLM gateway. "rules" = offline deterministic provider (no network).
    # Live providers: ollama | google | openai (any OpenAI-compatible server) | anthropic.  See .env.example.
    llm_provider: str = field(default_factory=lambda: os.environ.get("LLM_PROVIDER", "rules"))
    llm_api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY", ""))
    llm_base_url: str = field(default_factory=lambda: os.environ.get("LLM_BASE_URL", ""))      # blank = provider default
    # Model ids are configuration, blank = a provider default (verify against the provider's current model list).
    llm_model_small: str = field(default_factory=lambda: os.environ.get("LLM_MODEL_SMALL", ""))
    llm_model_mid: str = field(default_factory=lambda: os.environ.get("LLM_MODEL_MID", ""))
    llm_model_large: str = field(default_factory=lambda: os.environ.get("LLM_MODEL_LARGE", ""))
    llm_timeout: float = field(default_factory=lambda: _f("LLM_TIMEOUT_S", 180))
    llm_num_ctx: int = field(default_factory=lambda: int(_f("LLM_NUM_CTX", 16384)))             # Ollama context window (its default is far too small)
    llm_ollama_schema: bool = field(default_factory=lambda: os.environ.get("LLM_OLLAMA_SCHEMA", "0") == "1")
    llm_json_mode: bool = field(default_factory=lambda: os.environ.get("LLM_JSON_MODE", "1") == "1")
    llm_price_in_per_m: float = field(default_factory=lambda: _f("LLM_PRICE_IN_PER_M", 0))      # USD per 1M tokens; 0 = unmetered (local)
    llm_price_out_per_m: float = field(default_factory=lambda: _f("LLM_PRICE_OUT_PER_M", 0))
    # If the live provider fails, fall back to the rules baseline? Keep OFF for evals (it would hide failures).
    llm_breaker_threshold: int = field(default_factory=lambda: int(_f("LLM_BREAKER_THRESHOLD", 5)))
    llm_breaker_reset_s: float = field(default_factory=lambda: _f("LLM_BREAKER_RESET_S", 30))
    llm_allow_fallback: bool = field(default_factory=lambda: os.environ.get("LLM_ALLOW_FALLBACK", "0") == "1")
    budget_usd: dict = field(default_factory=lambda: {
        1: _f("BUDGET_USD_T1", 60), 2: _f("BUDGET_USD_T2", 30), 3: _f("BUDGET_USD_T3", 10), 4: _f("BUDGET_USD_T4", 3)})
    review_floor: float = field(default_factory=lambda: _f("SCREEN_REVIEW_FLOOR", 0.80))
    max_upload_bytes: int = field(default_factory=lambda: int(_f("MAX_UPLOAD_BYTES", 25_000_000)))
    max_pages: int = field(default_factory=lambda: int(_f("MAX_PAGES", 500)))
    webhook_secrets: dict = field(default_factory=lambda: {
        "sanctions-list-updated": os.environ.get("WEBHOOK_SECRET_SANCTIONS", "dev-secret-sanctions"),
        "vendor-portal": os.environ.get("WEBHOOK_SECRET_PORTAL", "dev-secret-portal")})
    # Dev tokens -> (user, role). Replace with OIDC at the gateway in production (plan §8.4).
    dev_auth: bool = field(default_factory=lambda: os.environ.get("VRO_DEV_AUTH", "1") == "1")

    def __post_init__(self) -> None:
        defaults = {"ollama": ("llama3.2:3b", "llama3.1:8b", "qwen2.5:14b"),
                    "google": ("gemini-2.0-flash", "gemini-2.0-flash", "gemini-2.5-pro"),
                    "openai": ("gpt-4o-mini", "gpt-4o-mini", "gpt-4o"),
                    "anthropic": ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5")}.get(self.llm_provider.lower(), ("rules-1",) * 3)
        self.llm_model_small = self.llm_model_small or defaults[0]
        self.llm_model_mid = self.llm_model_mid or defaults[1]
        self.llm_model_large = self.llm_model_large or defaults[2]

    def pdf_cfg(self) -> dict:
        return {"ocr": self.pdf_ocr, "langs": self.ocr_langs, "dpi": self.pdf_ocr_dpi, "ocr_max_pages": self.pdf_ocr_max_pages,
                "timeout": self.pdf_timeout_s, "mem_mb": self.pdf_mem_mb}
