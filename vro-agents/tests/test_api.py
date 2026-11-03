import base64
import hashlib
import hmac
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from evals.harness import load
from tests.asgi_client import Client
from tests.helpers import FROZEN, Base
from vro.api import build_app
from vro.util import set_now

SP, AN, SR, AML = "dev.u_sp.sponsor", "dev.u_an.analyst", "dev.u_senior.senior_analyst", "dev.u_aml.aml"
ADMIN1, ADMIN2 = "dev.u_ad1.admin", "dev.u_ad2.admin"


class ApiBase(Base):
    def setUp(self):
        super().setUp()
        self.app = build_app(self.svc)
        self.c = Client(self.app)

    def new_case(self, key="clean_t2", token=SP, patch=None):
        intake, _, docs = load(key)
        intake.update(patch or {})
        r = self.c.post("/v1/cases", json_body=intake, token=token)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["case_id"], docs

    def upload(self, cid, name, data, token=AN):
        return self.c.post(f"/v1/cases/{cid}/documents", json_body={"filename": name, "content_base64": base64.b64encode(data).decode()}, token=token)


class AuthAndValidation(ApiBase):
    def test_auth_rbac_validation(self):
        self.assertEqual(self.c.get("/v1/cases").status_code, 401)
        self.assertEqual(self.c.get("/v1/cases", token="dev.u.notarole").status_code, 401)
        intake, _, _ = load("clean_t2")
        self.assertEqual(self.c.post("/v1/cases", json_body=intake, token=AN).status_code, 403)
        bad = self.c.post("/v1/cases", json_body={"legal_name": "x"}, token=SP)
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(bad.json()["error"]["code"], "E_VALIDATION")
        self.assertEqual(self.c.post("/v1/cases", data=b"{not json", token=SP, headers={"content-type": "application/json"}).status_code, 400)
        extra = self.c.post("/v1/cases", json_body={**intake, "surprise": 1}, token=SP)
        self.assertEqual(extra.status_code, 422)          # strict contracts: unknown fields rejected

    def test_error_bodies_leak_no_internals(self):
        r = self.c.get("/v1/cases/nope", token=AN)
        self.assertEqual(r.status_code, 404)
        self.assertNotIn("Traceback", r.text)
        self.assertTrue(r.headers.get("x-trace-id"))

    def test_security_headers(self):
        r = self.c.get("/healthz")
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertIn("default-src 'self'", r.headers["content-security-policy"])

    def test_idempotent_create_and_gate(self):
        intake, _, _ = load("clean_t2")
        a = self.c.post("/v1/cases", json_body=intake, token=SP, headers={"Idempotency-Key": "abc"})
        b = self.c.post("/v1/cases", json_body=intake, token=SP, headers={"Idempotency-Key": "abc"})
        self.assertEqual(a.json()["case_id"], b.json()["case_id"])
        self.assertEqual(b.headers.get("idempotent-replay"), "true")
        self.assertEqual(len(self.c.get("/v1/cases", token=AN).json()["cases"]), 1)

    def test_tenant_isolation_over_http(self):
        cid, _ = self.new_case()
        self.assertEqual(self.c.get(f"/v1/cases/{cid}", token="dev.u_x.analyst.t_other").status_code, 404)
        self.assertEqual(self.c.get("/v1/cases", token="dev.u_x.analyst.t_other").json()["cases"], [])


class CaseFlowOverHttp(ApiBase):
    def test_full_flow_with_gates(self):
        cid, docs = self.new_case()
        for n, b in docs.items():
            self.assertEqual(self.upload(cid, n, b).status_code, 201)
        v = self.c.get(f"/v1/cases/{cid}", token=AN).json()
        self.assertEqual(v["case"]["state"], "TIERING")
        self.assertEqual(self.c.post(f"/v1/cases/{cid}/gates/G2", json_body={"decision": "CONFIRM", "rationale": "agree with the tier"}, token=AN).status_code, 403)
        r = self.c.post(f"/v1/cases/{cid}/gates/G2", json_body={"decision": "CONFIRM", "rationale": "agree with the tier"}, token=SR)
        self.assertEqual(r.json()["state"], "HUMAN_REVIEW")
        self.assertEqual(self.c.get(f"/v1/cases/{cid}/claims", token=AN).json()["claims"][0]["status"], "TRUSTED")
        self.assertEqual(self.c.get(f"/v1/cases/{cid}/packet", token=AN).status_code, 200)
        self.assertEqual(self.c.get(f"/v1/cases/{cid}/audit", token=AN).status_code, 200)
        self.assertEqual(self.c.get(f"/v1/cases/{cid}/documents/{v['documents'][0]['doc_id']}", token=AN).status_code, 200)
        k = self.c.get("/v1/kpis", token=AN).json()
        self.assertGreater(k["trusted_ratio"], 0.9)

    def test_packet_escapes_untrusted_vendor_text(self):
        evil = "Evil <script>alert(1)</script> Ltd"
        cid, docs = self.new_case(patch={"legal_name": evil, "business_owner": "<img src=x onerror=alert(1)>"})
        for n, b in docs.items():
            self.upload(cid, n, b)
        self.c.post(f"/v1/cases/{cid}/gates/G2", json_body={"decision": "CONFIRM", "rationale": "agree with the tier"}, token=SR)
        html = self.c.get(f"/v1/cases/{cid}/packet", token=AN).text
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_dev_scenario_loader(self):
        r = self.c.post("/v1/dev/scenarios/clean_t2/load", token=SP)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.c.post("/v1/dev/scenarios/nonexistent/load", token=SP).status_code, 404)
        self.assertEqual(self.c.post("/v1/dev/scenarios/../load", token=SP).status_code, 404)


class Webhooks(ApiBase):
    def sign(self, source, body: bytes, nonce="n1", ts="1000"):
        sec = self.svc.settings.webhook_secrets[source]
        sig = hmac.new(sec.encode(), ts.encode() + b"." + nonce.encode() + b"." + body, hashlib.sha256).hexdigest()
        return {"x-timestamp": ts, "x-nonce": nonce, "x-signature": sig}

    def test_signature_and_replay(self):
        body = json.dumps({"list_name": "SYNTHETIC_SDN", "entities": [{"entity_id": "Z1", "name": "Zork Holdings", "aliases": [], "country": "RU"}]}).encode()
        ok = self.c.post("/v1/webhooks/sanctions-list-updated", data=body, headers=self.sign("sanctions-list-updated", body))
        self.assertEqual(ok.status_code, 200, ok.text)
        replay = self.c.post("/v1/webhooks/sanctions-list-updated", data=body, headers=self.sign("sanctions-list-updated", body))
        self.assertEqual(replay.status_code, 409)
        h = self.sign("sanctions-list-updated", body, nonce="n2"); h["x-signature"] = "0" * 64
        self.assertEqual(self.c.post("/v1/webhooks/sanctions-list-updated", data=body, headers=h).status_code, 401)
        self.assertEqual(self.c.post("/v1/webhooks/unknown", data=body, headers=self.sign("sanctions-list-updated", body, "n3")).status_code, 404)

    def test_list_update_reopens_screening_for_onboarded_vendor(self):
        from evals.harness import drive
        r = drive(self.svc, self.svc and __import__("vro.workflow", fromlist=["Workflow"]).Workflow(self.svc), "clean_t2")
        self.assertEqual(r["state"], "MONITORING")
        ent = [{"entity_id": "Z1", "name": "Lumenta Analytics GmbH", "aliases": [], "country": "DE"}]
        body = json.dumps({"list_name": "SYNTHETIC_SDN", "entities": ent}).encode()
        out = self.c.post("/v1/webhooks/sanctions-list-updated", data=body, headers=self.sign("sanctions-list-updated", body, "n9"))
        self.assertEqual(out.status_code, 200, out.text)
        self.assertEqual(len(out.json()["cases_needing_review"]), 1)


class Admin(ApiBase):
    def test_kill_switch_halts_agents_then_resumes(self):
        self.assertEqual(self.c.post("/v1/admin/kill-switch", json_body={"on": True}, token=AN).status_code, 403)
        self.assertEqual(self.c.post("/v1/admin/kill-switch", json_body={"on": True}, token=ADMIN1).status_code, 200)
        cid, docs = self.new_case()
        self.c.post(f"/v1/cases/{cid}/gates/G2", json_body={"decision": "CONFIRM", "rationale": "agree with the tier"}, token=SR)
        for n, b in docs.items():
            r = self.upload(cid, n, b)
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error"]["code"], "E_KILL_SWITCH")
        self.assertEqual(self.c.get("/readyz").json()["kill_switch"], True)
        self.c.post("/v1/admin/kill-switch", json_body={"on": False}, token=ADMIN1)
        self.c.post(f"/v1/cases/{cid}/actions/advance", json_body={}, token=AN)
        self.assertEqual(self.c.get(f"/v1/cases/{cid}", token=AN).json()["case"]["state"], "HUMAN_REVIEW")

    def test_policy_activation_needs_four_eyes_and_passing_evals(self):
        r = self.c.post("/v1/admin/policy/requests", json_body={"pack": "default"}, token=ADMIN1)
        aid = r.json()["activation_id"]
        self.assertEqual(self.c.post(f"/v1/admin/policy/requests/{aid}/approve", token=ADMIN1, json_body={}).json()["error"]["code"], "E_4EYES")
        self.assertEqual(self.c.post(f"/v1/admin/policy/requests/{aid}/approve", token=ADMIN2, json_body={}).json()["error"]["code"], "E_EVAL_GATE")
        ev = self.c.post(f"/v1/admin/policy/requests/{aid}/eval", token=ADMIN1, json_body={})
        self.assertTrue(ev.json()["passed"], ev.text)
        ok = self.c.post(f"/v1/admin/policy/requests/{aid}/approve", token=ADMIN2, json_body={})
        self.assertEqual(ok.json()["status"], "ACTIVE")
        self.assertEqual(self.c.post("/v1/admin/policy/requests", json_body={"pack": "../../etc"}, token=ADMIN1).status_code, 404)

    def test_audit_export_is_restricted_and_verifiable(self):
        self.new_case()
        self.assertEqual(self.c.get("/v1/audit/export", token=AN).status_code, 403)
        r = self.c.get("/v1/audit/export", token="dev.u_aud.auditor")
        self.assertTrue(r.json()["chain"]["ok"])

    def test_metrics_and_ready(self):
        self.assertIsNone(self.c.get("/readyz").json()["audit_chain_ok"])         # readiness never scans the whole chain
        self.assertTrue(self.c.post("/v1/admin/audit/verify", token=ADMIN1, json_body={}).json()["ok"])
        self.assertEqual(self.c.get("/readyz").json()["audit_chain_ok"], True)
        self.assertIn("vro_http_requests_total", self.c.get("/metrics").text)


class UiStatic(unittest.TestCase):
    ROOT = Path(__file__).resolve().parent.parent / "ui"

    def test_untrusted_data_never_goes_through_innerhtml(self):
        js = (self.ROOT / "app.js").read_text()
        for m in re.finditer(r"\.innerHTML\s*=\s*([^;\n]+)", js):
            self.assertIn(m.group(1).strip(), ('""',), f"innerHTML assigned from data: {m.group(0)}")
        self.assertNotIn("insertAdjacentHTML", js)
        self.assertNotIn("eval(", js)
        self.assertNotIn("document.write", js)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_js_syntax(self):
        r = subprocess.run(["node", "--check", str(self.ROOT / "app.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_index_served(self):
        app = build_app(__import__("tests.helpers", fromlist=["fresh"]).fresh()[0])
        r = Client(app).get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Vendor Risk Onboarding", r.text)


if __name__ == "__main__":
    unittest.main()
