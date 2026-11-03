"""Command line: `python -m vro.cli <command>`. Operates on the same Workflow as the API (no business logic here)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agents.services import Services
from .config import Settings
from .models import GateDecision
from .policy import PolicyError
from .workflow import Actor, Workflow


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vro", description="Vendor risk onboarding")
    ap.add_argument("--tenant", default="t_demo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new-case"); s.add_argument("intake_json"); s.add_argument("--user", default="cli_sponsor")
    s = sub.add_parser("upload"); s.add_argument("case_id"); s.add_argument("path"); s.add_argument("--user", default="cli_analyst")
    s = sub.add_parser("show"); s.add_argument("case_id")
    sub.add_parser("list")
    s = sub.add_parser("decide"); s.add_argument("case_id"); s.add_argument("gate"); s.add_argument("decision"); s.add_argument("--role", required=True)
    s.add_argument("--user", required=True); s.add_argument("--why", required=True); s.add_argument("--tier", type=int)
    s = sub.add_parser("packet"); s.add_argument("case_id"); s.add_argument("--out", default="-")
    sub.add_parser("verify-audit")
    sub.add_parser("sweep")
    s = sub.add_parser("demo", help="load every synthetic scenario and print outcomes")
    sub.add_parser("serve").add_argument("--port", type=int, default=8000)
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("vro.api:create_app", factory=True, host="0.0.0.0", port=a.port)
        return 0
    svc = Services(Settings())
    wf = Workflow(svc)
    try:
        if a.cmd == "new-case":
            c = wf.create_case(Actor(a.user, "sponsor", a.tenant), json.loads(Path(a.intake_json).read_text()))
            print(json.dumps({"case_id": c["case_id"], "state": c["state"]}))
        elif a.cmd == "upload":
            p = Path(a.path)
            print(json.dumps(wf.upload_document(Actor(a.user, "analyst", a.tenant), a.case_id, p.name, p.read_bytes())))
        elif a.cmd == "show":
            from .packet import build
            print(json.dumps(build(svc, a.case_id), indent=1, default=str))
        elif a.cmd == "list":
            for r in svc.store.query("SELECT case_id, state, final_tier FROM cases WHERE tenant_id=?", (a.tenant,)):
                print(r["case_id"], r["state"], r["final_tier"])
        elif a.cmd == "decide":
            act = Actor(a.user, a.role, a.tenant)
            d = GateDecision(decision=a.decision, rationale=a.why, override_tier=a.tier)
            c = wf.decide_gate(act, a.case_id, a.gate, d)
            print(json.dumps({"state": c["state"]}))
        elif a.cmd == "packet":
            from .packet import build, render_html
            html = render_html(build(svc, a.case_id))
            sys.stdout.write(html) if a.out == "-" else Path(a.out).write_text(html)
        elif a.cmd == "verify-audit":
            r = svc.store.verify_audit_chain(); print(json.dumps(r)); return 0 if r["ok"] else 2
        elif a.cmd == "sweep":
            print(json.dumps(wf.sweep(a.tenant)))
        elif a.cmd == "demo":
            from evals.harness import drive
            from evals.runner import SCEN
            for k in SCEN:
                r = drive(svc, wf, k)
                print(f"{k:24s} {r['state']:12s} tier={r['final_tier']} band={r['band']} rules={','.join(r['rules'])}")
    except PolicyError as e:
        print(f"refused [{e.code}]: {e.message}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
