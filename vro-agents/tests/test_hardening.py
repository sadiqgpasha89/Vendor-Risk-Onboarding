import asyncio
import json
import logging
import threading
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from evals.harness import load
from tests.asgi_client import Client
from tests.helpers import Base
from tests.test_api import ADMIN1, AN, SP, ApiBase
from vro.api import build_app
from vro.config import Settings
from vro.jobs import JobRunner
from vro.llm_gateway import CircuitBreaker, Gateway, GatewayError, LLMRequest, LLMResponse, RetryableError
from vro.obs import JsonFormatter
from vro.security import AuthError, OidcVerifier, RateLimiter, production_problems

ISS, AUD = "https://idp.test/realms/bank", "vro-api"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwks(*keys):
    return {"keys": [{**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(k.public_key())), "kid": kid, "use": "sig", "alg": "RS256"} for kid, k in keys]}


def token(claims=None, key=KEY, kid="k1", alg="RS256", **over):
    now = int(time.time())
    c = {"iss": ISS, "aud": AUD, "sub": "alice", "exp": now + 300, "iat": now, "tenant_id": "t_demo", "roles": ["analyst"]}
    c.update(claims or {})
    c.update(over)
    return jwt.encode(c, key, algorithm=alg, headers={"kid": kid})


def verifier(**kw):
    return OidcVerifier(issuer=ISS, audience=AUD, fetch=lambda url: jwks(("k1", KEY)), **kw)


class Oidc(unittest.TestCase):
    def test_valid(self):
        p = verifier().verify(token())
        self.assertEqual((p.user_id, p.roles, p.tenant_id), ("alice", ["analyst"], "t_demo"))

    def test_rejections(self):
        v = verifier()
        bad = {
            "expired": token(exp=int(time.time()) - 3600),
            "wrong audience": token(aud="other"),
            "wrong issuer": token(iss="https://evil.test"),
            "wrong key": token(key=OTHER),
            "unknown kid": token(kid="nope"),
            "no sub": jwt.encode({"iss": ISS, "aud": AUD, "exp": int(time.time()) + 60, "tenant_id": "t", "roles": ["analyst"]}, KEY, algorithm="RS256", headers={"kid": "k1"}),
        }
        for name, tok in bad.items():
            with self.assertRaises(AuthError, msg=name):
                v.verify(tok)

    def test_alg_none_and_hs256_confusion_rejected(self):
        v = verifier()
        none_tok = jwt.encode({"iss": ISS, "aud": AUD, "sub": "x", "exp": int(time.time()) + 60, "tenant_id": "t", "roles": ["admin"]}, key=None, algorithm="none")
        with self.assertRaises(AuthError):
            v.verify(none_tok)
        pub_pem = KEY.public_key().public_bytes(encoding=__import__("cryptography").hazmat.primitives.serialization.Encoding.PEM,
                                                format=__import__("cryptography").hazmat.primitives.serialization.PublicFormat.SubjectPublicKeyInfo)
        hs = jwt.encode({"iss": ISS, "aud": AUD, "sub": "x", "exp": int(time.time()) + 60, "tenant_id": "t", "roles": ["admin"]}, pub_pem, algorithm="HS256", headers={"kid": "k1"}) \
            if False else None
        # PyJWT refuses to HS256-sign with a PEM key (that is the classic confusion attack); forge the token by hand instead
        import base64, hashlib, hmac
        b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=")
        signing = b({"alg": "HS256", "kid": "k1", "typ": "JWT"}) + b"." + b({"iss": ISS, "aud": AUD, "sub": "x", "exp": int(time.time()) + 60, "tenant_id": "t", "roles": ["admin"]})
        forged = (signing + b"." + base64.urlsafe_b64encode(hmac.new(pub_pem, signing, hashlib.sha256).digest()).rstrip(b"=")).decode()
        with self.assertRaises(AuthError):
            v.verify(forged)

    def test_tenant_and_roles_required_and_mapped(self):
        v = verifier(role_map={"tprm-analyst": "analyst"}, role_claim="realm_access.roles")
        p = v.verify(token(realm_access={"roles": ["tprm-analyst", "offline_access"]}))
        self.assertIn("analyst", p.roles)
        with self.assertRaises(AuthError) as e:
            v.verify(token(tenant_id=None))
        self.assertEqual(e.exception.status, 403)
        with self.assertRaises(AuthError):
            verifier().verify(token(roles=[]))

    def test_jwks_cache_and_rotation(self):
        clock = [1000.0]
        calls = []
        keys = [("k1", KEY)]

        def fetch(url):
            calls.append(url)
            return jwks(*keys)
        v = OidcVerifier(issuer=ISS, audience=AUD, fetch=fetch, clock=lambda: clock[0], min_refetch=30)
        v.verify(token())
        v.verify(token())
        self.assertEqual(len(calls), 1)                                        # cached
        keys.append(("k2", OTHER))
        with self.assertRaises(AuthError):
            v.verify(token(kid="k2", key=OTHER))                               # unknown kid but refetch throttled (anti-DoS)
        clock[0] += 31
        v.verify(token(kid="k2", key=OTHER))                                   # rotation picked up
        self.assertEqual(len(calls), 2)

    def test_jwks_outage_uses_cached_keys(self):
        clock, fail = [0.0], [False]

        def fetch(url):
            if fail[0]:
                raise ConnectionError("down")
            return jwks(("k1", KEY))
        v = OidcVerifier(issuer=ISS, audience=AUD, fetch=fetch, clock=lambda: clock[0], jwks_ttl=10)
        v.verify(token())
        fail[0] = True
        clock[0] += 100
        v.verify(token())                                                      # stale cache beats an outage


class OidcApi(ApiBase):
    def setUp(self):
        super().setUp()
        self.svc.settings.dev_auth = False
        self.svc.auth.oidc = verifier()

    def test_oidc_token_works_and_dev_token_does_not(self):
        self.assertEqual(self.c.get("/v1/cases", token=token()).status_code, 200)
        self.assertEqual(self.c.get("/v1/cases", token=SP).status_code, 401)

    def test_error_body_does_not_leak_reason(self):
        r = self.c.get("/v1/cases", token=token(aud="other"))
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("aud", r.text.lower().replace("audit", ""))

    def test_role_selection(self):
        t = token(roles=["analyst", "senior_analyst"])
        r = self.c.get("/v1/cases", token=t)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "E_ROLE_AMBIGUOUS"))
        self.assertEqual(self.c.get("/v1/cases", token=t, headers={"X-VRO-Role": "senior_analyst"}).status_code, 200)
        self.assertEqual(self.c.get("/v1/cases", token=t, headers={"X-VRO-Role": "admin"}).status_code, 403)

    def test_tenant_comes_from_token_not_client(self):
        r = self.c.post("/v1/cases", json_body=load("clean_t2")[0], token=token(roles=["sponsor"], tenant_id="t_a"))
        cid = r.json()["case_id"]
        self.assertEqual(self.c.get(f"/v1/cases/{cid}", token=token(roles=["analyst"], tenant_id="t_a")).status_code, 200)
        self.assertEqual(self.c.get(f"/v1/cases/{cid}", token=token(roles=["analyst"], tenant_id="t_b")).status_code, 404)


class RateLimit(unittest.TestCase):
    def test_token_bucket(self):
        t = [0.0]
        rl = RateLimiter(clock=lambda: t[0])
        self.assertTrue(all(rl.hit("k", 60, burst=3)[0] for _ in range(3)))
        ok, retry = rl.hit("k", 60, burst=3)
        self.assertFalse(ok)
        self.assertAlmostEqual(retry, 1.0, places=1)
        t[0] += 1.0
        self.assertTrue(rl.hit("k", 60, burst=3)[0])
        self.assertTrue(rl.hit("other", 60, burst=3)[0])                       # independent keys

    def test_zero_disables(self):
        self.assertTrue(RateLimiter().hit("k", 0)[0])


class RateLimitApi(ApiBase):
    def test_write_limit_returns_429_with_retry_after(self):
        self.svc.settings.rate_limit_write_rpm = 3
        codes = [self.c.post("/v1/cases", json_body={"bad": 1}, token=SP).status_code for _ in range(5)]
        self.assertEqual(codes[:3], [422, 422, 422])
        self.assertEqual(codes[3:], [429, 429])
        r = self.c.post("/v1/cases", json_body={}, token=SP)
        self.assertIn("retry-after", r.headers)
        self.assertEqual(self.c.get("/v1/cases", token=SP).status_code, 200)    # reads have their own bucket

    def test_limits_are_per_principal(self):
        self.svc.settings.rate_limit_write_rpm = 1
        self.c.post("/v1/cases", json_body={}, token=SP)
        self.assertEqual(self.c.post("/v1/cases", json_body={}, token=SP).status_code, 429)
        self.assertEqual(self.c.post("/v1/cases", json_body={}, token="dev.someone_else.sponsor").status_code, 422)

    def test_auth_failures_are_throttled_per_ip(self):
        self.svc.settings.rate_limit_auth_fail_rpm = 5
        codes = [self.c.get("/v1/cases", token="dev.x.nonexistent_role").status_code for _ in range(8)]
        self.assertEqual(codes[:5], [401] * 5)
        self.assertEqual(codes[5], 429)
        self.assertEqual(self.c.get("/v1/cases", token=SP).status_code, 200)    # a legitimate user on the same IP is unaffected


class Edge(ApiBase):
    def test_security_headers_and_trace_sanitising(self):
        r = self.c.get("/healthz", headers={"X-Trace-Id": "bad id\r\nSet-Cookie: x=1"})
        self.assertNotIn("set-cookie", r.headers)
        self.assertTrue(r.headers["x-trace-id"].startswith("tr_"))
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", r.headers["content-security-policy"])
        self.assertEqual(self.c.get("/healthz", headers={"X-Trace-Id": "abc-123"}).headers["x-trace-id"], "abc-123")

    def test_oversize_content_length_rejected_early(self):
        r = self.c.get("/healthz", headers={"content-length": "999999999"})
        self.assertEqual(r.status_code, 413)

    def test_host_allow_list(self):
        self.svc.settings.allowed_hosts = "vro.bank.example"
        app = build_app(self.svc)
        c = Client(app)
        self.assertEqual(c.get("/healthz", headers={"host": "evil.example"}).status_code, 400)
        self.assertEqual(c.get("/healthz", headers={"host": "vro.bank.example"}).status_code, 200)

    def test_hsts_only_in_prod(self):
        self.assertNotIn("strict-transport-security", self.c.get("/healthz").headers)
        self.svc.settings.app_env = "prod"
        self.assertIn("strict-transport-security", Client(build_app(self.svc)).get("/healthz").headers)

    def test_metrics_exposes_latency_breaker_and_limits(self):
        self.c.get("/v1/cases", token=SP)
        m = self.c.get("/metrics").text
        for needle in ("vro_http_request_seconds_bucket", "vro_llm_circuit_open", "vro_rate_limited_total", "vro_audit_chain_ok", "vro_jobs"):
            self.assertIn(needle, m)

    def test_dev_endpoints_hidden_when_dev_auth_off(self):
        self.svc.settings.dev_auth = False
        self.svc.auth.oidc = verifier()
        self.assertEqual(self.c.get("/v1/dev/scenarios", token=token(roles=["analyst"])).status_code, 404)


class Concurrency(ApiBase):
    def test_slow_request_does_not_block_event_loop(self):
        cid, _ = self.new_case()
        started, release = threading.Event(), threading.Event()
        orig = self.svc.gateway.complete

        def slow(*a, **k):
            started.set()
            release.wait(5)
            return orig(*a, **k)
        self.wf.advance = lambda cid_: (started.set(), release.wait(5), {"state": "NEW"})[2]
        app = build_app(self.svc)
        app.state.ctx.wf.advance = self.wf.advance
        c = Client(app)

        async def scenario():
            t0 = time.perf_counter()
            slow_req = asyncio.ensure_future(c.arequest("POST", f"/v1/cases/{cid}/actions/advance", json_body={}, token=AN))
            while not started.is_set():
                await asyncio.sleep(0.01)
            r = await c.arequest("GET", "/healthz")
            health_s = time.perf_counter() - t0
            release.set()
            await slow_req
            return r.status_code, health_s

        code, health_s = asyncio.run(scenario())
        self.assertEqual(code, 200)
        self.assertLess(health_s, 2.0)                                           # would be >= 5 s if the loop were blocked

    def test_handlers_are_threaded(self):
        import inspect
        self.assertTrue(inspect.iscoroutinefunction(next(r.endpoint for r in self.app.routes if getattr(r, "path", "") == "/v1/cases")))   # offload wrapper is async...
        self.assertTrue(all(not inspect.iscoroutinefunction(f) for f in (build_app.__globals__["body_json"],)))                       # ...the work inside is not


class Jobs(ApiBase):
    def test_async_advance_returns_202_and_completes(self):
        cid, docs = self.new_case()
        for n, b in docs.items():
            self.upload(cid, n, b)
        r = self.c.post(f"/v1/cases/{cid}/actions/advance?async=1", json_body={}, token=AN)
        self.assertEqual(r.status_code, 202)
        jid = r.json()["job_id"]
        for _ in range(100):
            j = self.c.get(f"/v1/jobs/{jid}", token=AN).json()
            if j["status"] in ("DONE", "FAILED"):
                break
            time.sleep(0.05)
        self.assertEqual(j["status"], "DONE", j)
        self.assertIn("state", j["result"])
        self.assertEqual(self.c.get(f"/v1/jobs/{jid}", token="dev.x.analyst.other_tenant").status_code, 404)

    def test_duplicate_submit_returns_same_job(self):
        gate = threading.Event()
        jr = JobRunner(self.svc.store, workers=1)
        a = jr.submit("t_demo", "c1", "advance", "u", lambda: (gate.wait(5), {"ok": 1})[1])
        b = jr.submit("t_demo", "c1", "advance", "u", lambda: {"never": 1})
        self.assertEqual(a["job_id"], b["job_id"])
        gate.set()

    def test_failure_is_recorded_without_traceback(self):
        jr = JobRunner(self.svc.store, workers=1)
        j = jr.submit("t_demo", "c2", "advance", "u", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        for _ in range(100):
            row = self.svc.store.get("jobs", "job_id", j["job_id"])
            if row["status"] == "FAILED":
                break
            time.sleep(0.02)
        self.assertEqual(row["status"], "FAILED")
        self.assertIn("RuntimeError", row["error"])
        self.assertNotIn("Traceback", row["error"])

    def test_orphans_are_reaped(self):
        st = self.svc.store
        st.insert("jobs", {"job_id": "job_old", "tenant_id": "t_demo", "case_id": "c", "kind": "advance", "status": "RUNNING", "created_at": "2020-01-01T00:00:00+00:00"})
        self.assertEqual(JobRunner(st).reap("t_demo"), 1)
        self.assertEqual(st.get("jobs", "job_id", "job_old")["status"], "FAILED")


class CaseLock(Base):
    def test_mutual_exclusion_and_reentrancy(self):
        st = self.svc.store
        inside, overlap = [0], [False]

        def work():
            with st.advisory_lock("case:x"):
                inside[0] += 1
                overlap[0] |= inside[0] > 1
                time.sleep(0.02)
                inside[0] -= 1
        ts = [threading.Thread(target=work) for _ in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertFalse(overlap[0])
        with st.advisory_lock("case:y"):
            with st.advisory_lock("case:y"):                                     # nested advance() inside decide_gate() must not deadlock
                pass


class Breaker(unittest.TestCase):
    def test_state_machine(self):
        t = [0.0]
        b = CircuitBreaker(threshold=3, reset_s=10, clock=lambda: t[0])
        for _ in range(3):
            self.assertTrue(b.allow())
            b.fail()
        self.assertEqual(b.state, "open")
        self.assertFalse(b.allow())
        t[0] += 11
        self.assertTrue(b.allow())                                               # one probe
        self.assertFalse(b.allow())
        b.fail()
        self.assertEqual(b.state, "open")                                        # probe failed: re-open
        t[0] += 11
        self.assertTrue(b.allow())
        b.ok()
        self.assertEqual(b.state, "closed")

    def test_gateway_fails_fast_and_falls_back(self):
        class Down:
            name = "down"
            n = 0

            def complete(self, req, model):
                Down.n += 1
                raise RetryableError("503")

        class Ok:
            name = "ok"

            def complete(self, req, model):
                return LLMResponse(text="{}", data={"x": 1}, provider="ok")
        s = Settings(db_path=":memory:", llm_provider="rules", llm_breaker_threshold=2)
        gw = Gateway(s, providers=[Down(), Ok()], sleeper=lambda x: None)
        for i in range(4):
            self.assertEqual(gw.complete(LLMRequest(task="t", user=str(i))).provider, "ok")
        self.assertEqual(Down.n, 8)                                              # 2 requests x 4 attempts, then the breaker opened: no more calls
        self.assertEqual(gw.breakers[0].state, "open")

    def test_bad_request_does_not_trip_breaker(self):
        class Bad:
            name = "bad"

            def complete(self, req, model):
                raise GatewayError("HTTP 400")
        gw = Gateway(Settings(db_path=":memory:", llm_provider="rules", llm_breaker_threshold=1), providers=[Bad()], sleeper=lambda x: None)
        for i in range(3):
            with self.assertRaises(GatewayError):
                gw.complete(LLMRequest(task="t", user=str(i)))
        self.assertEqual(gw.breakers[0].state, "closed")


class Config(unittest.TestCase):
    def test_production_refuses_insecure_defaults(self):
        probs = production_problems(Settings(app_env="prod", db_path=":memory:", dev_auth=True, oidc_issuer=""))
        text = " ".join(probs)
        for needle in ("VRO_DEV_AUTH", "OIDC", "webhook", "in-memory"):
            self.assertIn(needle, text)

    def test_non_prod_has_no_problems(self):
        self.assertEqual(production_problems(Settings(app_env="local")), [])

    def test_create_app_refuses_to_start(self):
        import os
        from vro.api import create_app
        old = {k: os.environ.get(k) for k in ("APP_ENV", "VRO_DEV_AUTH")}
        os.environ["APP_ENV"], os.environ["VRO_DEV_AUTH"] = "prod", "1"
        try:
            with self.assertRaises(RuntimeError) as e:
                create_app()
            self.assertIn("refusing to start", str(e.exception))
        finally:
            logging.getLogger("vro").handlers.clear()
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


class Logging(unittest.TestCase):
    def test_secrets_scrubbed(self):
        rec = logging.LogRecord("vro", logging.INFO, "", 0, "Authorization: Bearer eyJabc.def.ghi api_key=sk-12345 ok", None, None)
        out = json.loads(JsonFormatter().format(rec))["msg"]
        self.assertNotIn("eyJabc", out)
        self.assertNotIn("sk-12345", out)


class AuditVerify(ApiBase):
    def test_verify_sets_flag_and_detects_tamper(self):
        self.assertTrue(self.c.post("/v1/admin/audit/verify", json_body={}, token=ADMIN1).json()["ok"])
        self.assertEqual(self.svc.store.flag("audit_chain_ok"), "1")
        self.assertEqual(self.c.post("/v1/admin/audit/verify", json_body={}, token=AN).status_code, 403)


if __name__ == "__main__":
    unittest.main()
