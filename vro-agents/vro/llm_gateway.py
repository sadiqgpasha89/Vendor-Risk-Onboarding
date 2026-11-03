"""LLM gateway (plan §6.5, §6.9, §11.5): provider abstraction, routing by model tier, retries with backoff+jitter,
fallback provider, response cache, cassette record/replay, PII/secret redaction (GR-010), per-case budget with hard stop
and 80% alert (GR-012), and a kill switch (GR-016).

Providers:
  * RulesProvider     - offline deterministic task handlers (vro.offline). Default; needs no network or key.
  * AnthropicProvider - Messages API over HTTPS via `requests`. Model ids come from configuration (VERIFY against docs).
"""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from pydantic import BaseModel, ValidationError

from .config import Settings
from .store import Store
from .util import canonical_json, sha256_text


class GatewayError(Exception):
    pass


class RetryableError(GatewayError):
    pass


class BudgetExceeded(GatewayError):
    pass


class KillSwitchActive(GatewayError):
    pass


@dataclass
class LLMRequest:
    task: str                         # e.g. reader.extract, verifier.verify, synth.narrative, comms.draft
    system: str = ""
    user: str = ""
    schema: dict | None = None        # JSON schema the answer must satisfy
    tier: str = "mid"                 # small | mid | large
    temperature: float = 0.0
    max_tokens: int = 2000
    context: dict = field(default_factory=dict)   # structured inputs (used by the offline provider; never logged raw)
    agent: str = ""
    case_id: str | None = None
    tenant_id: str | None = None


@dataclass
class LLMResponse:
    text: str
    data: Any = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    model: str = ""
    provider: str = ""
    cached: bool = False


class Provider(Protocol):
    name: str
    def complete(self, req: LLMRequest, model: str) -> LLMResponse: ...


# ------------------------------------------------------------------------------- redaction (GR-010)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[ -]?)?(?:\(?\d{3}\)?[ -]?)\d{3}[ -]?\d{4}(?!\d)")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_KEY = re.compile(r"\b(?:sk|pk|api|key|token)[-_][A-Za-z0-9_\-]{16,}\b", re.I)
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def _luhn(num: str) -> bool:
    d = [int(c) for c in re.sub(r"\D", "", num)]
    if not 13 <= len(d) <= 19:
        return False
    s = 0
    for i, x in enumerate(reversed(d)):
        if i % 2:
            x = x * 2 - 9 if x * 2 > 9 else x * 2
        s += x
    return s % 10 == 0


def redact(text: str) -> str:
    text = _KEY.sub("[SECRET]", text)
    text = _SSN.sub("[SSN]", text)
    text = _CARD.sub(lambda m: "[CARD]" if _luhn(m.group(0)) else m.group(0), text)
    text = _IBAN.sub("[IBAN]", text)
    text = _EMAIL.sub("[EMAIL]", text)
    text = _PHONE.sub("[PHONE]", text)
    return text


# ------------------------------------------------------------------------------- providers
class RulesProvider:
    """Deterministic offline provider: dispatches to registered task handlers. NOT a language model; it is the
    rule-based baseline that lets the whole pipeline run, be tested and be evaluated without network access."""
    name = "rules"

    def __init__(self, handlers: dict[str, Callable[[LLMRequest], Any]] | None = None):
        if handlers is None:
            from . import offline
            handlers = offline.TASKS
        self.handlers = handlers

    def complete(self, req: LLMRequest, model: str) -> LLMResponse:
        h = self.handlers.get(req.task)
        if not h:
            raise GatewayError(f"rules provider has no handler for task '{req.task}'")
        data = h(req)
        text = json.dumps(data, default=str)
        return LLMResponse(text=text, data=data, tokens_in=len(req.user) // 4, tokens_out=len(text) // 4,
                           cost_usd=0.0, model="rules-1", provider=self.name)


def extract_json(text: str) -> Any:
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except ValueError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            return json.loads(m.group(0))
        raise


# ------------------------------------------------------------------------------- circuit breaker
class CircuitBreaker:
    """Fail fast when a provider is down. closed -> (N consecutive infrastructure failures) -> open for `reset_s` -> half-open (one probe)
    -> closed on success / open again on failure. Only RetryableError counts: a 400 caused by one bad request must not take the model offline."""
    def __init__(self, threshold: int = 5, reset_s: float = 30.0, clock: Callable[[], float] = time.monotonic):
        self.threshold, self.reset_s, self.clock = threshold, reset_s, clock
        self.fails, self.opened_at, self.probing = 0, None, False

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        return "half_open" if self.clock() - self.opened_at >= self.reset_s else "open"

    def allow(self) -> bool:
        st = self.state
        if st == "closed":
            return True
        if st == "half_open" and not self.probing:
            self.probing = True
            return True
        return False

    def ok(self) -> None:
        self.fails, self.opened_at, self.probing = 0, None, False

    def fail(self) -> None:
        self.fails += 1
        self.probing = False
        if self.fails >= self.threshold or self.opened_at is not None:
            self.opened_at = self.clock()


# ------------------------------------------------------------------------------- budget
class Budget:
    def __init__(self, limit_usd: float, alert_cb: Callable[[float, float], None] | None = None):
        self.limit, self.spent, self.alerted, self.cb = limit_usd, 0.0, False, alert_cb

    def check(self) -> None:
        if self.spent >= self.limit:
            raise BudgetExceeded(f"case budget ${self.limit:.2f} exhausted (spent ${self.spent:.4f})")

    def charge(self, cost: float) -> None:
        self.spent += cost
        if not self.alerted and self.limit > 0 and self.spent >= 0.8 * self.limit:
            self.alerted = True
            if self.cb:
                self.cb(self.spent, self.limit)


# ------------------------------------------------------------------------------- gateway
class Gateway:
    def __init__(self, settings: Settings, store: Store | None = None, providers: list[Provider] | None = None,
                 sleeper: Callable[[float], None] = time.sleep, cassette: str | None = None, cassette_mode: str = "off"):
        self.s, self.store, self.sleep = settings, store, sleeper
        if providers is None:
            providers = self.build_providers(settings)
        self.providers = providers
        self.breakers = [CircuitBreaker(settings.llm_breaker_threshold, settings.llm_breaker_reset_s) for _ in providers]
        self.cache: dict[str, LLMResponse] = {}
        self.cassette_path = Path(cassette) if cassette else None
        self.cassette_mode = cassette_mode            # off | record | replay
        self._cassette: dict[str, dict] = {}
        if self.cassette_path and cassette_mode == "replay" and self.cassette_path.exists():
            for line in self.cassette_path.read_text().splitlines():
                d = json.loads(line)
                self._cassette[d["key"]] = d
        self.budgets: dict[str, Budget] = {}
        self.stats = {"calls": 0, "retries": 0, "fallbacks": 0, "cache_hits": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "latency_s": 0.0,
                      "by_provider": {}, "by_task": {}}

    @staticmethod
    def build_providers(settings: Settings) -> list[Provider]:
        """rules -> offline baseline. Anything else -> LiveProvider over the chosen backend (+ rules fallback only if LLM_ALLOW_FALLBACK=1)."""
        if settings.llm_provider.lower() == "rules":
            return [RulesProvider()]
        from .llm_backends import make_backend
        from .llm_live import LiveProvider
        provs: list[Provider] = [LiveProvider(make_backend(settings), settings)]
        if settings.llm_allow_fallback:
            provs.append(RulesProvider())
        return provs

    def model_for(self, tier: str) -> str:
        return {"small": self.s.llm_model_small, "mid": self.s.llm_model_mid, "large": self.s.llm_model_large}[tier]

    def budget_for(self, case_id: str, tier: int | None = None) -> Budget:
        if case_id not in self.budgets:
            limit = self.s.budget_usd.get(tier or 2, self.s.budget_usd[2])
            def alert(spent, lim, cid=case_id):
                if self.store:
                    self.store.audit(None, "gateway", "system", "budget_alert_80pct", "case", cid, {"spent": spent, "limit": lim})
            self.budgets[case_id] = Budget(limit, alert)
        return self.budgets[case_id]

    def _key(self, req: LLMRequest, model: str) -> str:
        return sha256_text(canonical_json([req.task, model, req.system, req.user, req.schema, req.context, req.temperature]))

    def complete(self, req: LLMRequest) -> LLMResponse:
        if self.store:
            if self.store.flag("kill_switch") == "1":
                raise KillSwitchActive("global kill switch is active")
            if req.agent and self.store.flag(f"kill:{req.agent}") == "1":
                raise KillSwitchActive(f"agent {req.agent} is disabled")
        model = self.model_for(req.tier)
        budget = self.budget_for(req.case_id) if req.case_id else None
        if budget:
            budget.check()
        # redaction before anything leaves the process or is logged (GR-010)
        safe = LLMRequest(**{**req.__dict__, "system": redact(req.system), "user": redact(req.user)})
        key = self._key(safe, model)
        if key in self.cache:
            self.stats["cache_hits"] += 1
            return LLMResponse(**{**self.cache[key].__dict__, "cached": True, "cost_usd": 0.0})
        if self.cassette_mode == "replay":
            if key not in self._cassette:
                raise GatewayError(f"cassette miss for task {req.task} (run with cassette_mode=record to refresh)")
            d = self._cassette[key]
            return LLMResponse(text=d["text"], data=d.get("data"), model=d.get("model", ""), provider="cassette", cached=True)
        last: Exception | None = None
        for pi, prov in enumerate(self.providers):
            br = self.breakers[pi]
            if not br.allow():
                last = GatewayError(f"circuit open for provider {getattr(prov, 'name', pi)}")
                if pi + 1 < len(self.providers):
                    self.stats["fallbacks"] += 1
                continue
            for attempt in range(4):
                try:
                    self.stats["calls"] += 1
                    t0 = time.perf_counter()
                    resp = prov.complete(safe, model)
                    self._record(prov, safe, resp, time.perf_counter() - t0)
                    br.ok()
                    if budget:
                        budget.charge(resp.cost_usd)
                    self.cache[key] = resp
                    if len(self.cache) > 2000:
                        self.cache.pop(next(iter(self.cache)))
                    if self.cassette_mode == "record" and self.cassette_path:
                        with self.cassette_path.open("a") as f:
                            f.write(json.dumps({"key": key, "text": resp.text, "data": resp.data, "model": resp.model}, default=str) + "\n")
                    return resp
                except RetryableError as e:
                    last = e
                    self.stats["retries"] += 1
                    if attempt == 3:
                        br.fail()
                        break
                    self.sleep(min(30.0, (2 ** attempt) * 0.5) * (0.5 + random.random() / 2))   # backoff + jitter
                except GatewayError as e:
                    last = e
                    br.probing = False
                    break
            if pi + 1 < len(self.providers):
                self.stats["fallbacks"] += 1
        raise GatewayError(f"all providers failed for {req.task}: {last}")

    def _record(self, prov: Provider, req: LLMRequest, resp: LLMResponse, dt: float) -> None:
        st = self.stats
        st["tokens_in"] += resp.tokens_in
        st["tokens_out"] += resp.tokens_out
        st["cost_usd"] = round(st["cost_usd"] + resp.cost_usd, 6)
        st["latency_s"] = round(st["latency_s"] + dt, 3)
        for bucket, key in (("by_provider", resp.provider or prov.name), ("by_task", req.task)):
            st[bucket][key] = st[bucket].get(key, 0) + 1

    def structured(self, req: LLMRequest, model_cls: type[BaseModel] | None = None) -> Any:
        """Complete + parse + validate against a pydantic model; one repair attempt with the validation error fed back."""
        resp = self.complete(req)
        for attempt in range(2):
            try:
                data = resp.data if resp.data is not None else extract_json(resp.text)
                return model_cls.model_validate(data) if model_cls else data
            except (ValidationError, ValueError) as e:
                if attempt == 1:
                    raise GatewayError(f"structured output invalid after repair: {str(e)[:300]}") from e
                repair = LLMRequest(**{**req.__dict__, "user": req.user + f"\n\nYour previous answer was invalid: {str(e)[:500]}. Return corrected JSON only."})
                resp = self.complete(repair)
        raise GatewayError("unreachable")
