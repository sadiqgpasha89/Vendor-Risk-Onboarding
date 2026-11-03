"""Chat backends for the live LLM path: Ollama (local), Google Gemini, OpenAI-compatible (OpenAI, vLLM, LM Studio, llama.cpp,
LiteLLM...) and Anthropic. Each turns (system, user) into text + token counts. Nothing here knows about vendors or tasks;
task logic lives in `llm_live.py`.

NOT RUN in the authoring environment (no model access). The request/response shapes follow each vendor's public REST docs
as of authoring; if a provider changes its API, only the matching class here needs touching. Provide keys via env only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from .config import Settings
from .llm_gateway import GatewayError, RetryableError


@dataclass
class ChatResult:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


class ChatBackend(Protocol):
    name: str

    def chat(self, system: str, user: str, model: str, *, schema: dict | None = None, max_tokens: int = 2000, temperature: float = 0.0) -> ChatResult: ...


def _post(url: str, body: dict, headers: dict, timeout: float, verify: bool | str = True) -> dict:
    import requests  # lazy: only needed on the live path
    try:
        r = requests.post(url, json=body, headers=headers, timeout=timeout, verify=verify)
    except requests.RequestException as e:
        raise RetryableError(f"network error: {type(e).__name__}") from e
    if r.status_code in (408, 409, 425, 429) or r.status_code >= 500:
        raise RetryableError(f"HTTP {r.status_code}")
    if r.status_code >= 400:
        # never echo request bodies (they hold vendor text); the response snippet is the provider's error message
        raise GatewayError(f"HTTP {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except ValueError as e:
        raise RetryableError("provider returned non-JSON") from e


class OllamaBackend:
    """Local models via Ollama. `ollama serve` then `ollama pull <model>`. Structured outputs: pass the JSON schema as `format`."""
    name = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434", timeout: float = 300.0, num_ctx: int = 16384, use_schema: bool = True):
        self.base, self.timeout, self.num_ctx, self.use_schema = base_url.rstrip("/"), timeout, num_ctx, use_schema

    def chat(self, system, user, model, *, schema=None, max_tokens=2000, temperature=0.0) -> ChatResult:
        body: dict[str, Any] = {"model": model, "stream": False,
                                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                                "options": {"temperature": temperature, "num_ctx": self.num_ctx, "num_predict": max_tokens},
                                "format": schema if (schema and self.use_schema) else "json"}
        j = _post(f"{self.base}/api/chat", body, {"content-type": "application/json"}, self.timeout)
        return ChatResult(j.get("message", {}).get("content", ""), int(j.get("prompt_eval_count", 0)), int(j.get("eval_count", 0)))


class GoogleBackend:
    """Google Gemini via the Generative Language API (API key from Google AI Studio). JSON mode via responseMimeType."""
    name = "google"

    def __init__(self, api_key: str, base_url: str = "https://generativelanguage.googleapis.com", timeout: float = 120.0):
        if not api_key:
            raise GatewayError("LLM_API_KEY is required for the google provider")
        self.key, self.base, self.timeout = api_key, base_url.rstrip("/"), timeout

    def chat(self, system, user, model, *, schema=None, max_tokens=2000, temperature=0.0) -> ChatResult:
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens, "responseMimeType": "application/json"}}
        # key travels in a header, not the URL, so it cannot leak into access logs or tracebacks
        j = _post(f"{self.base}/v1beta/models/{model}:generateContent", body, {"content-type": "application/json", "x-goog-api-key": self.key}, self.timeout)
        cands = j.get("candidates") or []
        if not cands:
            raise GatewayError(f"no candidates returned (promptFeedback={json.dumps(j.get('promptFeedback', {}))[:200]})")
        if cands[0].get("finishReason") in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"):
            raise GatewayError(f"blocked by provider: {cands[0].get('finishReason')}")
        text = "".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", []))
        u = j.get("usageMetadata", {})
        return ChatResult(text, int(u.get("promptTokenCount", 0)), int(u.get("candidatesTokenCount", 0)))


class OpenAICompatBackend:
    """Any /v1/chat/completions server: OpenAI, Azure-style gateways, vLLM, LM Studio, llama.cpp server, LiteLLM, OpenRouter."""
    name = "openai"

    def __init__(self, api_key: str = "", base_url: str = "https://api.openai.com", timeout: float = 120.0, json_mode: bool = True):
        self.key, self.base, self.timeout, self.json_mode = api_key, base_url.rstrip("/"), timeout, json_mode

    def chat(self, system, user, model, *, schema=None, max_tokens=2000, temperature=0.0) -> ChatResult:
        body: dict[str, Any] = {"model": model, "temperature": temperature, "max_tokens": max_tokens,
                                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"content-type": "application/json"}
        if self.key:
            headers["authorization"] = f"Bearer {self.key}"
        url = self.base + ("/chat/completions" if self.base.endswith("/v1") else "/v1/chat/completions")
        j = _post(url, body, headers, self.timeout)
        ch = (j.get("choices") or [{}])[0]
        u = j.get("usage", {})
        return ChatResult(ch.get("message", {}).get("content") or "", int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0)))


class AnthropicBackend:
    name = "anthropic"

    def __init__(self, api_key: str, base_url: str = "https://api.anthropic.com", timeout: float = 120.0):
        if not api_key:
            raise GatewayError("LLM_API_KEY is required for the anthropic provider")
        self.key, self.base, self.timeout = api_key, base_url.rstrip("/"), timeout

    def chat(self, system, user, model, *, schema=None, max_tokens=2000, temperature=0.0) -> ChatResult:
        body = {"model": model, "max_tokens": max_tokens, "temperature": temperature, "system": system, "messages": [{"role": "user", "content": user}]}
        j = _post(f"{self.base}/v1/messages", body, {"x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"}, self.timeout)
        text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
        u = j.get("usage", {})
        return ChatResult(text, int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0)))


def make_backend(s: Settings) -> ChatBackend:
    p = s.llm_provider.lower()
    if p == "ollama":
        return OllamaBackend(s.llm_base_url or "http://localhost:11434", s.llm_timeout, s.llm_num_ctx, s.llm_ollama_schema)
    if p in ("google", "gemini"):
        return GoogleBackend(s.llm_api_key, s.llm_base_url or "https://generativelanguage.googleapis.com", s.llm_timeout)
    if p in ("openai", "openai_compat", "vllm", "lmstudio"):
        return OpenAICompatBackend(s.llm_api_key, s.llm_base_url or "https://api.openai.com", s.llm_timeout, s.llm_json_mode)
    if p == "anthropic":
        return AnthropicBackend(s.llm_api_key, s.llm_base_url or "https://api.anthropic.com", s.llm_timeout)
    raise GatewayError(f"unknown LLM_PROVIDER '{s.llm_provider}' (use rules|ollama|google|openai|anthropic)")
