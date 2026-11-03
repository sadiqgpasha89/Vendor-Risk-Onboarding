"""Copy a SQLite VRO database into Postgres, then verify the audit chain. NOT run against a live Postgres by the authors.

    python -m tools.migrate_sqlite_to_pg --sqlite data/vro.db --dsn postgresql://admin@host/vro [--embed-dim 512] [--dry-run]

Run it once, against an empty database, with the app stopped. Audit rows keep their original seq and hashes so the chain still verifies.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

from vro.store import JSON_COLS
from vro.store_pg import PgStore, q_ident

AUDIT = "audit_events"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", required=True)
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--embed-dim", type=int, default=512)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    src = sqlite3.connect(a.sqlite)
    src.row_factory = sqlite3.Row
    pg = PgStore(a.dsn, embed_dim=a.embed_dim, migrate=True)
    tables = [r["name"] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    if AUDIT not in tables:
        print(f"no {AUDIT} table in the SQLite file; is this a VRO database?", file=sys.stderr)
        return 2
    tables.sort(key=lambda t: (t == AUDIT, t))                    # audit last
    total = 0
    for t in tables:
        rows = [dict(r) for r in src.execute(f"SELECT * FROM {q_ident(t)}" + (" ORDER BY seq" if t == AUDIT else ""))]
        for r in rows:
            if t == AUDIT:
                if not a.dry_run:                                   # payload stays exact TEXT; seq is preserved
                    cols = list(r)
                    with pg._conn() as c:
                        c.execute(f"INSERT INTO {AUDIT}({','.join(q_ident(x) for x in cols)}) OVERRIDING SYSTEM VALUE VALUES({','.join(['%s'] * len(cols))})", [r[x] for x in cols])
                continue
            for k, v in list(r.items()):
                if k in JSON_COLS and isinstance(v, str) and v:
                    try:
                        r[k] = json.loads(v)
                    except ValueError:
                        pass
            if not a.dry_run:
                pg.insert(t, r)
        print(f"{t}: {len(rows)} rows")
        total += len(rows)
    ok = True
    if not a.dry_run:
        with pg._conn() as c:
            c.execute(f"SELECT setval(pg_get_serial_sequence('{AUDIT}','seq'), COALESCE((SELECT MAX(seq) FROM {AUDIT}),1))")
        res = pg.verify_audit_chain()
        ok = bool(res[0] if isinstance(res, tuple) else res)
    print("total rows:", total, "| audit chain verifies:", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
