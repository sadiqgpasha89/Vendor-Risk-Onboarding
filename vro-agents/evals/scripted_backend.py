"""A fake chat backend that answers the live provider's prompts using the offline extractors. It is NOT a model. It exists so the
live-provider plumbing (prompt building, JSON parsing, hardening, verifier downgrade-only rule, budgets/metrics) can be exercised
without network access: `python -m evals.live --backend scripted`. Behaviour knobs let tests simulate a misbehaving model."""
from __future__ import annotations

import json
import re

from vro import offline
from vro.llm_backends import ChatResult


class ScriptedBackend:
    name = "scripted"

    def __init__(self, mode: str = "faithful", verifier: str = "confirm", narrative: str | None = None):
        self.mode, self.verifier, self.narrative = mode, verifier, narrative
        self.calls: list[dict] = []

    # ------------------------------------------------------------------------------------------------
    def chat(self, system, user, model, *, schema=None, max_tokens=2000, temperature=0.0) -> ChatResult:
        self.calls.append({"system": system, "user": user, "model": model})
        if '"fields": [{"name"' in user:
            out = self._reader(user)
        elif "Verify each claim strictly" in user:
            out = self._verifier(user)
        elif "assessment narrative" in user:
            out = {"narrative": self.narrative or "Evidence suggests the residual risk requires human review."}
        elif "Draft the message" in user:
            out = {"body": "DRAFT - NOT SENT.\n\nPlease provide the listed documents."}
        else:
            out = {}
        text = out if isinstance(out, str) else json.dumps(out)
        return ChatResult(text, len(user) // 4, len(text) // 4)

    # ------------------------------------------------------------------------------------------------
    def _reader(self, user: str) -> dict:
        doc_id = re.search(r'"doc_id": "([^"]+)"', user).group(1)
        dt = re.search(r'"doc_type": "([^"]+)"', user).group(1)
        body = user.split("<untrusted_document", 1)[1]
        pages = [p for p in re.split(r"\[\[PAGE \d+\]\]\n", body)[1:]]
        pages = [p.split("</untrusted_document>")[0] for p in pages]
        base = offline.EXTRACTORS[dt](pages) if dt in offline.EXTRACTORS else {"fields": [], "lists": {}}
        fields, lists = [dict(f) for f in base["fields"]], {k: [dict(i) for i in v] for k, v in base["lists"].items()}
        if dt == "financial_statements":
            fields = [f for f in fields if f["name"] != "current_ratio"]
            for nm, rx in (("total_current_assets_usd", r"total\s+current\s+assets[^\n]*"), ("total_current_liabilities_usd", r"total\s+current\s+liabilities[^\n]*")):
                h = offline._hit(pages, re.compile(rx, re.I))
                fields.append(offline._field(nm, offline._money(h[1].split(":", 1)[-1]) if h else None, h))
        if self.mode == "hallucinate":
            for f in fields:
                if f["found"]:
                    f["quote"] = "The auditors confirm every control operated effectively throughout the entire period without exception."
                    break
            for i in lists.get("clauses", []):
                if not i["present"]:
                    i["present"] = True
                    i["quote"] = "The vendor shall provide unlimited audit rights to the bank at all times."
                    break
        if self.mode == "obey_injection":
            flags = ["embedded_instruction_detected"] if "ignore all previous" in user.lower() else []
            return {"doc_id": doc_id, "doc_type": dt, "fields": fields, "lists": lists, "flags": flags}
        return {"doc_id": doc_id, "doc_type": dt, "fields": fields, "lists": lists, "flags": []}

    def _verifier(self, user: str) -> dict:
        ids = re.findall(r"### claim_id: (\S+)", user)
        if self.verifier == "confirm":
            return {"verdicts": [{"claim_id": i, "verdict": "SUPPORTED", "defect": None} for i in ids]}
        if self.verifier == "reject_all":
            return {"verdicts": [{"claim_id": i, "verdict": "UNSUPPORTED", "defect": "scripted rejection"} for i in ids]}
        if self.verifier == "omit":
            return {"verdicts": []}
        if self.verifier == "garbage_verdict":
            return {"verdicts": [{"claim_id": i, "verdict": "LOOKS_FINE", "defect": None} for i in ids]}
        raise ValueError(self.verifier)
