import json
import unittest
from unittest import mock

from evals.harness import drive
from evals.scripted_backend import ScriptedBackend
from vro.agents.services import Services
from vro.config import Settings
from vro.llm_backends import (AnthropicBackend, GoogleBackend, OllamaBackend, OpenAICompatBackend, make_backend)
from vro.llm_gateway import Gateway, GatewayError, LLMRequest, RetryableError, extract_json
from vro.llm_live import LiveProvider, normalise_extraction
from vro.workflow import Workflow
from vro.util import set_now
from evals.runner import FROZEN


def live_svc(backend=None, **kw):
    set_now(FROZEN)
    s = Settings(db_path=":memory:", llm_provider="ollama", app_env="test")
    be = backend or ScriptedBackend(**kw)
    gw = Gateway(s, providers=[LiveProvider(be, s)])
    svc = Services(s, gateway=gw)
    return svc, Workflow(svc), be


class LiveEndToEnd(unittest.TestCase):
    def tearDown(self):
        set_now(None)

    def test_clean_scenario_matches_rules_baseline(self):
        svc, wf, be = live_svc()
        r = drive(svc, wf, "clean_t2")
        self.assertEqual(r["state"], "MONITORING")
        self.assertEqual(r["band"], "LOW")
        self.assertGreater(len(be.calls), 5)
        self.assertGreater(svc.gateway.stats["tokens_in"], 0)

    def test_contract_gaps_still_found(self):
        svc, wf, _ = live_svc()
        r = drive(svc, wf, "contract_gaps")
        self.assertTrue(any(x.startswith("CON-") for x in r["rules"]), r["rules"])

    def test_hallucinated_quotes_never_become_claims(self):
        svc, wf, _ = live_svc(mode="hallucinate")
        r = drive(svc, wf, "contract_gaps")
        bad = svc.store.query("SELECT quote FROM claim_evidence WHERE quote LIKE '%unlimited audit rights%' OR quote LIKE '%every control operated effectively%'")
        self.assertEqual(bad, [])

    def test_verifier_cannot_rescue_tampered_claim(self):
        svc, wf, _ = live_svc(verifier="confirm")      # lenient model confirms everything
        drive(svc, wf, "clean_t2")
        from vro.agents import verifier as va
        case = svc.store.query("SELECT * FROM cases")[0]
        claims = svc.ledger.get_claims(case["tenant_id"], case["vendor_id"], status="TRUSTED", with_evidence=True)
        c = next(c for c in claims if c["evidence"][0]["source_type"] == "document" and not (c["evidence"][0]["locator"] or "").startswith("absence:"))
        items = va.build_items(svc, [c])
        items[0]["evidence"][0]["quote"] = "The vendor guarantees unlimited liability for all losses in every circumstance."
        v = svc.gateway.complete(LLMRequest(task="verifier.verify", context={"items": items}, agent="A10")).data["verdicts"][0]["verdict"]
        self.assertNotEqual(v, "SUPPORTED")

    def test_model_can_downgrade_and_fails_closed(self):
        for mode in ("reject_all", "omit", "garbage_verdict"):
            svc, wf, _ = live_svc(verifier=mode)
            r = drive(svc, wf, "clean_t2", finish=False)
            n_trusted_doc = svc.store.query("SELECT COUNT(*) n FROM claims c JOIN claim_evidence e ON e.claim_id=c.claim_id WHERE c.status='TRUSTED' AND e.source_type='document'")[0]["n"]
            self.assertEqual(n_trusted_doc, 0, mode)

    def test_narrative_with_invented_numbers_is_replaced(self):
        svc, wf, _ = live_svc(narrative="Residual risk is 99.5 which is fine.")
        r = drive(svc, wf, "clean_t2", finish=False)
        a = svc.store.query("SELECT narrative FROM assessments")
        self.assertTrue(a and "99.5" not in a[-1]["narrative"])
        self.assertGreaterEqual(svc.gateway.providers[0].stats["degraded"], 1)

    def test_injection_text_is_inside_untrusted_block_and_flagged(self):
        svc, wf, be = live_svc(mode="obey_injection")
        r = drive(svc, wf, "injection_visible")
        reader_calls = [c for c in be.calls if '"fields": [{"name"' in c["user"]]
        for c in reader_calls:
            i = c["user"].lower().find("ignore all previous")
            if i >= 0:
                self.assertGreater(i, c["user"].find("<untrusted_document"))
        self.assertIn("DOC-001", r["rules"])


class Normalise(unittest.TestCase):
    CTX = {"doc_id": "d1", "doc_type": "bcp_dr", "pages": ["RTO: 4 hours\nLast DR test: 2026-03-01\nRegions: US, EU"], "had_injection": False}

    def test_coercion_and_page_correction(self):
        raw = {"fields": [{"name": "rto_hours", "value": "4", "found": True, "page": 9, "quote": "RTO: 4 hours"},
                          {"name": "dr_last_tested", "value": "Never", "found": True, "page": 1, "quote": "Last DR test: 2026-03-01"}]}
        out = normalise_extraction(raw, self.CTX)
        f = {x["name"]: x for x in out["fields"]}
        self.assertEqual(f["rto_hours"]["value"], 4.0)
        self.assertEqual(f["rto_hours"]["page"], 1)       # model said 9; code corrected it
        self.assertFalse(f["rpo_hours"]["found"])

    def test_unverifiable_quote_drops_field(self):
        raw = {"fields": [{"name": "rto_hours", "value": 1, "found": True, "page": 1, "quote": "RTO: 1 hour guaranteed"}]}
        out = normalise_extraction(raw, self.CTX)
        self.assertFalse(out["fields"][0]["found"])
        self.assertIn("quote_unverifiable:rto_hours", out["flags"])

    def test_ratio_computed_in_code(self):
        ctx = {"doc_id": "d", "doc_type": "financial_statements", "pages": ["Total current assets: $500,000\nTotal current liabilities: $250,000"], "had_injection": False}
        raw = {"fields": [{"name": "total_current_assets_usd", "value": 500000, "found": True, "page": 1, "quote": "Total current assets: $500,000"},
                          {"name": "total_current_liabilities_usd", "value": 250000, "found": True, "page": 1, "quote": "Total current liabilities: $250,000"},
                          {"name": "current_ratio", "value": 99, "found": True, "page": 1, "quote": "Total current assets: $500,000"}]}
        out = normalise_extraction(raw, ctx)
        self.assertEqual({f["name"]: f["value"] for f in out["fields"]}["current_ratio"], 2.0)

    def test_deterministic_injection_flag_is_authoritative(self):
        out = normalise_extraction({"fields": []}, {**self.CTX, "had_injection": True})
        self.assertIn("embedded_instruction_detected", out["flags"])


class Backends(unittest.TestCase):
    def _resp(self, status, body):
        m = mock.Mock(status_code=status, text=json.dumps(body))
        m.json.return_value = body
        return m

    def test_ollama(self):
        with mock.patch("requests.post", return_value=self._resp(200, {"message": {"content": "{}"}, "prompt_eval_count": 7, "eval_count": 3})) as p:
            r = OllamaBackend().chat("s", "u", "llama3.1:8b")
        self.assertEqual((r.tokens_in, r.tokens_out), (7, 3))
        url, body = p.call_args.args[0], p.call_args.kwargs["json"]
        self.assertTrue(url.endswith("/api/chat"))
        self.assertEqual(body["format"], "json")
        self.assertFalse(body["stream"])
        self.assertGreaterEqual(body["options"]["num_ctx"], 8192)

    def test_google_key_in_header_not_url(self):
        j = {"candidates": [{"content": {"parts": [{"text": "{}"}]}, "finishReason": "STOP"}], "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2}}
        with mock.patch("requests.post", return_value=self._resp(200, j)) as p:
            r = GoogleBackend("SECRETKEY").chat("s", "u", "gemini-2.0-flash")
        self.assertNotIn("SECRETKEY", p.call_args.args[0])
        self.assertEqual(p.call_args.kwargs["headers"]["x-goog-api-key"], "SECRETKEY")
        self.assertEqual(r.tokens_in, 5)

    def test_google_safety_block(self):
        j = {"candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]}
        with mock.patch("requests.post", return_value=self._resp(200, j)):
            with self.assertRaises(GatewayError):
                GoogleBackend("k").chat("s", "u", "m")

    def test_openai_compat_url_and_auth(self):
        j = {"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 4, "completion_tokens": 1}}
        with mock.patch("requests.post", return_value=self._resp(200, j)) as p:
            OpenAICompatBackend("k", "http://localhost:1234/v1").chat("s", "u", "m")
        self.assertEqual(p.call_args.args[0], "http://localhost:1234/v1/chat/completions")
        self.assertEqual(p.call_args.kwargs["headers"]["authorization"], "Bearer k")

    def test_anthropic(self):
        j = {"content": [{"type": "text", "text": "{}"}], "usage": {"input_tokens": 3, "output_tokens": 2}}
        with mock.patch("requests.post", return_value=self._resp(200, j)):
            self.assertEqual(AnthropicBackend("k").chat("s", "u", "m").tokens_out, 2)

    def test_error_mapping(self):
        with mock.patch("requests.post", return_value=self._resp(429, {})):
            with self.assertRaises(RetryableError):
                OllamaBackend().chat("s", "u", "m")
        with mock.patch("requests.post", return_value=self._resp(400, {})):
            with self.assertRaises(GatewayError):
                OllamaBackend().chat("s", "u", "m")

    def test_make_backend_and_defaults(self):
        self.assertIsInstance(make_backend(Settings(llm_provider="ollama")), OllamaBackend)
        self.assertIsInstance(make_backend(Settings(llm_provider="google", llm_api_key="k")), GoogleBackend)
        self.assertIsInstance(make_backend(Settings(llm_provider="openai")), OpenAICompatBackend)
        with self.assertRaises(GatewayError):
            make_backend(Settings(llm_provider="nonsense"))
        with self.assertRaises(GatewayError):
            make_backend(Settings(llm_provider="google", llm_api_key=""))
        self.assertTrue(Settings(llm_provider="ollama").llm_model_mid)

    def test_think_blocks_stripped(self):
        self.assertEqual(extract_json("<think>hmm {x}</think>\n```json\n{\"a\": 1}\n```"), {"a": 1})


if __name__ == "__main__":
    unittest.main()


class RedactionSafety(unittest.TestCase):
    def test_phone_like_claim_ids_survive_redaction(self):
        # regression: a 10-digit run inside a hex claim id was redacted as a phone number, so the model's verdict never matched
        from vro.llm_gateway import redact
        self.assertNotEqual(redact("c_7d9748292289451d"), "c_7d9748292289451d")      # proves the hazard is real
        svc, wf, be = live_svc()
        drive(svc, wf, "clean_t2", finish=False)
        for c in be.calls:
            if "Verify each claim" in c["user"]:
                self.assertNotIn("c_", c["user"].split("Verify each claim", 1)[1].split("###", 1)[1][:30])
