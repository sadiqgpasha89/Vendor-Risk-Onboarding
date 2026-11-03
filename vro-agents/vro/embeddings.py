"""Real embedding providers behind the `Embedder` protocol used by retrieval (default stays the offline HashingEmbedder).

    EMBED_PROVIDER=ollama  EMBED_MODEL=nomic-embed-text      VRO_EMBED_DIM=768    (ollama pull nomic-embed-text)
    EMBED_PROVIDER=google  EMBED_MODEL=text-embedding-004    VRO_EMBED_DIM=768    (uses EMBED_API_KEY or LLM_API_KEY)
    EMBED_PROVIDER=openai  EMBED_MODEL=text-embedding-3-small VRO_EMBED_DIM=1536

VRO_EMBED_DIM must equal the model's output size; it also sizes the pgvector column. Changing model or dimension means re-indexing every
document (chunks store vectors from one model only). NOT RUN against a real service in the authoring environment; request shapes follow the
vendors' public REST docs and are unit tested with a mocked transport. Embeddings of vendor text go to the provider you configure: choose
a local provider (ollama) if that text may not leave your network.
"""
from __future__ import annotations

import numpy as np

from .config import Settings
from .llm_backends import _post
from .llm_gateway import GatewayError

BATCH = 32


def _norm(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=1, keepdims=True)
    return (m / np.maximum(n, 1e-9)).astype(np.float32)


class _Base:
    dim: int
    name = "base"

    def _call(self, batch: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH):
            got = self._call([t if t.strip() else " " for t in texts[i:i + BATCH]])
            if len(got) != len(texts[i:i + BATCH]):
                raise GatewayError(f"{self.name}: expected {len(texts[i:i + BATCH])} embeddings, got {len(got)}")
            out.extend(got)
        m = np.asarray(out, dtype=np.float32)
        if m.shape[1] != self.dim:
            raise GatewayError(f"{self.name}: model returned {m.shape[1]}-dim vectors but VRO_EMBED_DIM={self.dim}; fix the setting (and re-index)")
        return _norm(m)


class OllamaEmbedder(_Base):
    name = "ollama"

    def __init__(self, model: str, dim: int, base_url: str = "http://localhost:11434", timeout: float = 120.0):
        self.model, self.dim, self.base, self.timeout = model, dim, base_url.rstrip("/"), timeout

    def _call(self, batch):
        j = _post(f"{self.base}/api/embed", {"model": self.model, "input": batch}, {"content-type": "application/json"}, self.timeout)
        return j.get("embeddings", [])


class GoogleEmbedder(_Base):
    name = "google"

    def __init__(self, model: str, dim: int, api_key: str, base_url: str = "https://generativelanguage.googleapis.com", timeout: float = 120.0):
        if not api_key:
            raise GatewayError("EMBED_API_KEY (or LLM_API_KEY) is required for google embeddings")
        self.model, self.dim, self.key, self.base, self.timeout = model, dim, api_key, base_url.rstrip("/"), timeout

    def _call(self, batch):
        body = {"requests": [{"model": f"models/{self.model}", "content": {"parts": [{"text": t}]}} for t in batch]}
        j = _post(f"{self.base}/v1beta/models/{self.model}:batchEmbedContents", body, {"content-type": "application/json", "x-goog-api-key": self.key}, self.timeout)
        return [e.get("values", []) for e in j.get("embeddings", [])]


class OpenAIEmbedder(_Base):
    name = "openai"

    def __init__(self, model: str, dim: int, api_key: str = "", base_url: str = "https://api.openai.com", timeout: float = 120.0):
        self.model, self.dim, self.key, self.base, self.timeout = model, dim, api_key, base_url.rstrip("/"), timeout

    def _call(self, batch):
        h = {"content-type": "application/json", **({"authorization": f"Bearer {self.key}"} if self.key else {})}
        url = self.base + ("/embeddings" if self.base.endswith("/v1") else "/v1/embeddings")
        j = _post(url, {"model": self.model, "input": batch}, h, self.timeout)
        return [d["embedding"] for d in sorted(j.get("data", []), key=lambda d: d.get("index", 0))]


def make_embedder(s: Settings):
    p = s.embed_provider.lower()
    if p in ("", "hashing", "rules"):
        from .retrieval import HashingEmbedder
        return HashingEmbedder(s.embed_dim)
    key = s.embed_api_key or s.llm_api_key
    base = s.embed_base_url
    if p == "ollama":
        return OllamaEmbedder(s.embed_model or "nomic-embed-text", s.embed_dim, base or "http://localhost:11434")
    if p in ("google", "gemini"):
        return GoogleEmbedder(s.embed_model or "text-embedding-004", s.embed_dim, key, base or "https://generativelanguage.googleapis.com")
    if p in ("openai", "openai_compat"):
        return OpenAIEmbedder(s.embed_model or "text-embedding-3-small", s.embed_dim, key, base or "https://api.openai.com")
    raise GatewayError(f"unknown EMBED_PROVIDER '{s.embed_provider}' (hashing|ollama|google|openai)")
