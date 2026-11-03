"""Authentication (OIDC/JWT), rate limiting and production start-up validation.

OIDC: the API validates bearer JWTs issued by YOUR identity provider (Keycloak, Entra ID, Okta, Auth0, Google Workspace...). It never issues
tokens and never stores passwords. Validation: signature against the issuer's JWKS, algorithm allow-list (RS256/ES256 only, so `none` and
HS* key-confusion are impossible), iss, aud, exp, nbf, sub required, 60 s leeway. Roles come from a configurable claim, are mapped to
internal roles, and a user holding several may choose the active one with `X-VRO-Role` (it must be one of their token's roles).

NOT RUN against a real IdP in the authoring environment; unit tests use locally generated RSA keys and an injected JWKS fetcher.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable


class AuthError(Exception):
    """Raised for any authentication problem. `reason` is for server logs only; clients get a generic message."""
    def __init__(self, reason: str, status: int = 401):
        super().__init__(reason)
        self.reason, self.status = reason, status


@dataclass
class Principal:
    user_id: str
    roles: list[str]
    tenant_id: str
    claims: dict


def _dig(d: dict, path: str) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


class OidcVerifier:
    ALGS = ("RS256", "ES256")

    def __init__(self, *, issuer: str, audience: str, jwks_url: str = "", role_claim: str = "roles", tenant_claim: str = "tenant_id",
                 role_map: dict[str, str] | None = None, leeway: int = 60, jwks_ttl: int = 600, min_refetch: int = 30,
                 fetch: Callable[[str], dict] | None = None, clock: Callable[[], float] = time.time):
        if not issuer or not audience:
            raise ValueError("OIDC_ISSUER and OIDC_AUDIENCE are required")
        self.issuer, self.audience = issuer, audience
        self.jwks_url = jwks_url or issuer.rstrip("/") + "/.well-known/jwks.json"
        self.role_claim, self.tenant_claim, self.role_map = role_claim, tenant_claim, role_map or {}
        self.leeway, self.ttl, self.min_refetch, self.clock = leeway, jwks_ttl, min_refetch, clock
        self._fetch = fetch or self._http_fetch
        self._keys: dict[str, dict] = {}
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def _http_fetch(url: str) -> dict:
        import requests
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        return r.json()

    def _key_for(self, kid: str | None):
        import jwt
        with self._lock:
            now = self.clock()
            stale = now - self._fetched_at > self.ttl
            if (stale or kid not in self._keys) and (now - self._fetched_at > self.min_refetch or not self._keys):
                try:
                    self._keys = {k.get("kid"): k for k in self._fetch(self.jwks_url).get("keys", [])}
                    self._fetched_at = now
                except Exception as e:  # noqa: BLE001
                    if not self._keys:
                        raise AuthError(f"jwks fetch failed: {type(e).__name__}") from e     # keep serving with cached keys if we have them
            jwk = self._keys.get(kid) if kid is not None else (next(iter(self._keys.values())) if len(self._keys) == 1 else None)
        if jwk is None:
            raise AuthError("unknown signing key")
        return jwt.PyJWK(jwk).key

    def verify(self, token: str) -> Principal:
        import jwt
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in self.ALGS:
                raise AuthError(f"disallowed alg {header.get('alg')!r}")
            claims = jwt.decode(token, self._key_for(header.get("kid")), algorithms=list(self.ALGS), audience=self.audience, issuer=self.issuer,
                                leeway=self.leeway, options={"require": ["exp", "iss", "aud", "sub"]})
        except AuthError:
            raise
        except jwt.PyJWTError as e:
            raise AuthError(f"invalid token: {type(e).__name__}") from e
        tenant = _dig(claims, self.tenant_claim)
        if not tenant or not isinstance(tenant, str):
            raise AuthError("token has no tenant claim", 403)
        raw = _dig(claims, self.role_claim)
        raw = [raw] if isinstance(raw, str) else (raw if isinstance(raw, list) else [])
        roles = sorted({self.role_map.get(r, r) for r in raw if isinstance(r, str)})
        if not roles:
            raise AuthError("token has no usable roles", 403)
        return Principal(str(claims["sub"]), roles, tenant, claims)

    @classmethod
    def from_settings(cls, s) -> "OidcVerifier | None":
        if not s.oidc_issuer:
            return None
        return cls(issuer=s.oidc_issuer, audience=s.oidc_audience, jwks_url=s.oidc_jwks_url, role_claim=s.oidc_role_claim,
                   tenant_claim=s.oidc_tenant_claim, role_map=json.loads(s.oidc_role_map or "{}"))


# --------------------------------------------------------------------------------------------- rate limiting
class RateLimiter:
    """In-process token bucket. One instance per replica => the effective limit is N x replicas; use RedisRateLimiter for a shared limit."""
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock, self._b, self._lock = clock, {}, threading.Lock()

    def hit(self, key: str, per_minute: int, burst: int | None = None) -> tuple[bool, float]:
        """Returns (allowed, retry_after_seconds)."""
        if per_minute <= 0:
            return True, 0.0
        cap, rate = float(burst or per_minute), per_minute / 60.0
        with self._lock:
            now = self.clock()
            tokens, last = self._b.get(key, (cap, now))
            tokens = min(cap, tokens + (now - last) * rate)
            if tokens >= 1.0:
                self._b[key] = (tokens - 1.0, now)
                if len(self._b) > 50_000:                       # bound memory under key-spraying
                    self._prune(now, cap, rate)
                return True, 0.0
            self._b[key] = (tokens, now)
            return False, (1.0 - tokens) / rate

    def _prune(self, now: float, cap: float, rate: float) -> None:
        for k in [k for k, (t, last) in self._b.items() if t + (now - last) * rate >= cap]:
            del self._b[k]


class RedisRateLimiter:
    """Shared fixed-window limiter (pip install redis). Same interface as RateLimiter. Fails OPEN on Redis errors so a cache outage is not an
    outage of the platform; the failure is counted in the `vro_ratelimit_backend_errors_total` metric."""
    def __init__(self, url: str, errors: Callable[[], None] | None = None):
        import redis
        self.r, self.errors = redis.Redis.from_url(url, socket_timeout=0.2), errors or (lambda: None)

    def hit(self, key: str, per_minute: int, burst: int | None = None) -> tuple[bool, float]:
        if per_minute <= 0:
            return True, 0.0
        window = int(time.time() // 60)
        k = f"vro:rl:{key}:{window}"
        try:
            pipe = self.r.pipeline()
            pipe.incr(k)
            pipe.expire(k, 70)
            n = pipe.execute()[0]
        except Exception:  # noqa: BLE001
            self.errors()
            return True, 0.0
        return (n <= (burst or per_minute)), (60 - time.time() % 60)


def make_limiter(settings) -> Any:
    if getattr(settings, "redis_url", ""):
        return RedisRateLimiter(settings.redis_url)
    return RateLimiter()


# --------------------------------------------------------------------------------------------- production start-up checks
def production_problems(s) -> list[str]:
    """Things that must be true before the API serves real traffic. Returned as a list so ops sees every problem at once."""
    p: list[str] = []
    if s.app_env not in ("prod", "production", "staging"):
        return p
    if s.dev_auth:
        p.append("VRO_DEV_AUTH must be 0: dev bearer tokens grant any role to anyone")
    if not s.oidc_issuer:
        p.append("OIDC_ISSUER / OIDC_AUDIENCE must be configured")
    if any(v.startswith(("dev-secret", "change-me")) for v in s.webhook_secrets.values()):
        p.append("webhook secrets are still the defaults (WEBHOOK_SECRET_*)")
    if not s.database_url and s.db_path == ":memory:":
        p.append("database is in-memory: data would be lost on restart")
    if s.llm_provider == "rules" and s.app_env in ("prod", "production"):
        p.append("LLM_PROVIDER=rules is a keyword baseline, not a model: acceptable only as a deliberate degraded mode")
    return p
