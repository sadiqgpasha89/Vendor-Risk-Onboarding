"""Export JSON Schemas for every contract model (R8: contract-first). CI fails if the committed schemas drift from the code."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from vro import models

NAMES = ["VendorIntake", "Evidence", "Claim", "Finding", "Question", "AgentResult", "DocExtraction", "GateDecision", "TierProposal", "ScreeningRecommendation"]


def render() -> dict[str, str]:
    return {f"{n}.schema.json": json.dumps(getattr(models, n).model_json_schema(), indent=1, sort_keys=True) + "\n" for n in NAMES}


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "contracts"
    out.mkdir(exist_ok=True)
    want = render()
    if "--check" in sys.argv:
        bad = [k for k, v in want.items() if not (out / k).exists() or (out / k).read_text() != v]
        print("contracts drifted:" if bad else "contracts in sync", bad or "")
        sys.exit(1 if bad else 0)
    for k, v in want.items():
        (out / k).write_text(v)
    print(f"wrote {len(want)} schemas to {out}")
