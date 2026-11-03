"""SQLite persistence (stand-in for Postgres, plan §3.7) + append-only hash-chained audit log.

Every query that touches tenant data takes tenant_id (application-level equivalent of row-level security).
The audit table rejects UPDATE/DELETE via triggers; `verify_audit_chain` detects tampering.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from .util import canonical_json, iso, new_id, now, sha256_text

DB_ERRORS: tuple = (sqlite3.DatabaseError,)     # vro.store_pg extends this with the Postgres driver's error type

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenant(tenant_id TEXT PRIMARY KEY, name TEXT, policy_pack TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS vendor(vendor_id TEXT PRIMARY KEY, tenant_id TEXT, legal_name TEXT, trade_names TEXT,
  country_iso2 TEXT, reg_number TEXT, lei TEXT, website TEXT, status TEXT, tier INTEGER, created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_vendor_tenant ON vendor(tenant_id);
CREATE TABLE IF NOT EXISTS ownership_edge(edge_id TEXT PRIMARY KEY, tenant_id TEXT, case_id TEXT, child_name TEXT,
  parent_name TEXT, pct REAL, is_person INTEGER, country_iso2 TEXT, source TEXT, as_of TEXT);
CREATE TABLE IF NOT EXISTS cases(case_id TEXT PRIMARY KEY, tenant_id TEXT, vendor_id TEXT, requester_id TEXT,
  state TEXT NOT NULL, intake TEXT, proposed_tier INTEGER, final_tier INTEGER, jurisdictions TEXT, emergency INTEGER,
  sla_due_at TEXT, preparer_id TEXT, context TEXT, hold_reason TEXT, conditional_expires TEXT, created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_cases_tenant ON cases(tenant_id, state);
CREATE TABLE IF NOT EXISTS documents(doc_id TEXT PRIMARY KEY, tenant_id TEXT, case_id TEXT, vendor_id TEXT, doc_type TEXT,
  filename TEXT, mime TEXT, sha256 TEXT, size INTEGER, quarantine_status TEXT, hidden_text_flag INTEGER,
  injection_flags TEXT, page_count INTEGER, period_start TEXT, period_end TEXT, valid_until TEXT, supersedes_doc_id TEXT,
  uploaded_by TEXT, uploaded_at TEXT, raw_text TEXT, clean_text TEXT, language TEXT, version INTEGER, processed INTEGER DEFAULT 0,
  ocr_quality TEXT, parse_meta TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ux_doc_vendor_sha ON documents(vendor_id, sha256);
CREATE TABLE IF NOT EXISTS doc_chunks(chunk_id TEXT PRIMARY KEY, tenant_id TEXT, doc_id TEXT, vendor_id TEXT, parent_chunk_id TEXT,
  level INTEGER, strategy TEXT, section_path TEXT, page_from INTEGER, page_to INTEGER, text TEXT, token_count INTEGER,
  embedding BLOB, meta TEXT, chunker_version TEXT);
CREATE INDEX IF NOT EXISTS ix_chunks_doc ON doc_chunks(doc_id);
CREATE INDEX IF NOT EXISTS ix_chunks_vendor ON doc_chunks(tenant_id, vendor_id);
CREATE TABLE IF NOT EXISTS claims(claim_id TEXT PRIMARY KEY, tenant_id TEXT, vendor_id TEXT, case_id TEXT, subject TEXT,
  predicate TEXT, object TEXT, statement TEXT, status TEXT NOT NULL CHECK(status IN('TRUSTED','STALE','UNTRUSTED','REFUTED','SUPERSEDED')),
  confidence REAL, produced_by TEXT, prompt_version TEXT, version INTEGER, policy_version TEXT, valid_until TEXT,
  created_at TEXT, last_verified_at TEXT, stale_reason TEXT);
CREATE INDEX IF NOT EXISTS ix_claims_vendor ON claims(tenant_id, vendor_id, status);
CREATE TABLE IF NOT EXISTS claim_evidence(evidence_id TEXT PRIMARY KEY, claim_id TEXT, source_type TEXT, doc_id TEXT,
  chunk_id TEXT, page INTEGER, locator TEXT, quote TEXT, quote_hash TEXT, source_sha256 TEXT, source_version TEXT,
  retrieved_at TEXT, stance TEXT);
CREATE INDEX IF NOT EXISTS ix_ev_claim ON claim_evidence(claim_id);
CREATE TABLE IF NOT EXISTS claim_versions(claim_id TEXT, version INTEGER, statement TEXT, status TEXT, changed_by TEXT,
  change_reason TEXT, changed_at TEXT, PRIMARY KEY(claim_id, version, changed_at));
CREATE TABLE IF NOT EXISTS screening_results(screening_id TEXT PRIMARY KEY, tenant_id TEXT, case_id TEXT, subject_name TEXT,
  subject_role TEXT, list_name TEXT, list_version TEXT, match_entity_id TEXT, match_name TEXT, score REAL, features TEXT,
  auto_disposition TEXT, recommendation TEXT, explanation TEXT, human_disposition TEXT, dispositioned_by TEXT, rationale TEXT,
  created_at TEXT);
CREATE TABLE IF NOT EXISTS assessments(assessment_id TEXT PRIMARY KEY, tenant_id TEXT, case_id TEXT, scoring_version TEXT,
  inherent TEXT, control_effectiveness TEXT, residual TEXT, tier INTEGER, overrides TEXT, narrative TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS findings(finding_id TEXT PRIMARY KEY, tenant_id TEXT, case_id TEXT, domain TEXT, severity TEXT,
  title TEXT, description TEXT, claim_ids TEXT, regulation_refs TEXT, remediation TEXT, status TEXT, owner TEXT, due_date TEXT,
  rule_id TEXT, disputed INTEGER DEFAULT 0, disputed_by TEXT, disputed_reason TEXT, disposition TEXT, disposition_by TEXT,
  exception_expires TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS questions(question_id TEXT PRIMARY KEY, tenant_id TEXT, case_id TEXT, to_role TEXT, text TEXT,
  why TEXT, blocking INTEGER, options TEXT, status TEXT, answer TEXT, answered_by TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS approvals(approval_id TEXT PRIMARY KEY, tenant_id TEXT, case_id TEXT, gate TEXT, approver_id TEXT,
  decision TEXT, conditions TEXT, rationale TEXT, decided_at TEXT);
CREATE TABLE IF NOT EXISTS gate_tasks(task_id TEXT PRIMARY KEY, tenant_id TEXT, case_id TEXT, gate TEXT, status TEXT,
  role_required TEXT, created_at TEXT, due_at TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS agent_runs(run_id TEXT PRIMARY KEY, tenant_id TEXT, case_id TEXT, agent TEXT, model TEXT,
  prompt_version TEXT, status TEXT, idempotency_key TEXT UNIQUE, input_hash TEXT, output TEXT, tokens_in INTEGER,
  tokens_out INTEGER, cost_usd REAL, latency_ms INTEGER, trace_id TEXT, started_at TEXT);
CREATE TABLE IF NOT EXISTS tool_calls(call_id TEXT PRIMARY KEY, run_id TEXT, tool TEXT, args_redacted TEXT, result_hash TEXT,
  status TEXT, latency_ms INTEGER, started_at TEXT);
CREATE TABLE IF NOT EXISTS audit_events(seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, tenant_id TEXT, actor TEXT,
  actor_type TEXT, action TEXT, entity_type TEXT, entity_id TEXT, payload TEXT, prev_hash TEXT, hash TEXT);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT,'audit_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT,'audit_events is append-only'); END;
CREATE TABLE IF NOT EXISTS nonces(source TEXT, nonce TEXT, ts TEXT, PRIMARY KEY(source, nonce));
CREATE TABLE IF NOT EXISTS idempotency(key TEXT PRIMARY KEY, tenant_id TEXT, response TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS flags(name TEXT PRIMARY KEY, value TEXT, updated_by TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS drafts(draft_id TEXT PRIMARY KEY, tenant_id TEXT, case_id TEXT, kind TEXT, body TEXT,
  status TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS feedback(feedback_id TEXT PRIMARY KEY, tenant_id TEXT, case_id TEXT, kind TEXT, ref TEXT,
  note TEXT, user TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS policy_activations(activation_id TEXT PRIMARY KEY, tenant_id TEXT, pack TEXT, status TEXT,
  requested_by TEXT, approved_by TEXT, eval_passed INTEGER, created_at TEXT, decided_at TEXT);
CREATE TABLE IF NOT EXISTS list_versions(list_name TEXT PRIMARY KEY, version TEXT, loaded_at TEXT, entity_count INTEGER);
CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY, tenant_id TEXT, case_id TEXT, kind TEXT, status TEXT, requested_by TEXT,
  result TEXT, error TEXT, created_at TEXT, started_at TEXT, finished_at TEXT);
CREATE INDEX IF NOT EXISTS ix_jobs_case ON jobs(case_id, status);
"""

JSON_COLS = {"trade_names", "intake", "jurisdictions", "context", "injection_flags", "object", "features",
             "inherent", "control_effectiveness", "residual", "overrides", "claim_ids", "regulation_refs",
             "options", "payload", "output", "result", "parse_meta", "args_redacted", "conditions", "meta", "response", "role_required", "stale_changes"}


def _enc(k: str, v: Any):
    if k in JSON_COLS:  # JSON columns always hold JSON text, so str values round-trip unchanged
        return None if v is None else json.dumps(v, default=str)
    if isinstance(v, bool):
        return int(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _dec(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k in list(d):
        if k in JSON_COLS and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except (ValueError, TypeError):
                pass
    return d


class Store:
    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self._klocks: dict[str, threading.RLock] = {}
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL") if path != ":memory:" else None
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.executescript(SCHEMA)
            self._add_missing_columns()

    @contextmanager
    def advisory_lock(self, key: str):
        """Mutual exclusion on a named resource (one case at a time). Re-entrant within a thread. PgStore uses pg_advisory_lock so it also
        excludes other API replicas."""
        with self.lock:
            lk = self._klocks.setdefault(key, threading.RLock())
        with lk:
            yield

    def set_tenant(self, tenant_id: str | None) -> None:
        """No-op on SQLite (see PgStore)."""

    @contextmanager
    def tenant_scope(self, tenant_id: str | None):
        """No-op here (tenant filtering is in the queries). PgStore uses it to drive row-level security."""
        yield

    def _add_missing_columns(self) -> None:
        """Forward-only column additions for databases created by an older build (CREATE TABLE IF NOT EXISTS never alters a table)."""
        have = {r["name"] for r in self.db.execute("PRAGMA table_info(documents)").fetchall()}
        for col in ("ocr_quality", "parse_meta"):
            if col not in have:
                self.db.execute(f"ALTER TABLE documents ADD COLUMN {col} TEXT")

    # ---- generic helpers -------------------------------------------------
    @contextmanager
    def tx(self):
        with self.lock:
            self.db.execute("BEGIN")
            try:
                yield
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def insert(self, table: str, row: dict) -> None:
        cols = list(row)
        with self.lock:
            self.db.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                            [_enc(c, row[c]) for c in cols])

    def update(self, table: str, key_col: str, key: Any, changes: dict) -> None:
        if not changes:
            return
        cols = list(changes)
        with self.lock:
            self.db.execute(f"UPDATE {table} SET {','.join(c + '=?' for c in cols)} WHERE {key_col}=?",
                            [_enc(c, changes[c]) for c in cols] + [key])

    def get(self, table: str, key_col: str, key: Any) -> dict | None:
        with self.lock:
            return _dec(self.db.execute(f"SELECT * FROM {table} WHERE {key_col}=?", (key,)).fetchone())

    def query(self, sql: str, params: Iterable = ()) -> list[dict]:
        with self.lock:
            return [_dec(r) for r in self.db.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: Iterable = ()) -> None:
        with self.lock:
            self.db.execute(sql, tuple(params))

    # ---- audit chain -------------------------------------------------------
    def audit(self, tenant_id: str | None, actor: str, actor_type: str, action: str, entity_type: str,
              entity_id: str | None, payload: dict | None = None) -> int:
        with self.lock:
            last = self.db.execute("SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
            prev = last["hash"] if last else "0" * 64
            ts = iso(now())
            body = {"ts": ts, "tenant_id": tenant_id, "actor": actor, "actor_type": actor_type, "action": action,
                    "entity_type": entity_type, "entity_id": entity_id, "payload": payload or {}}
            h = sha256_text(prev + canonical_json(body))
            cur = self.db.execute(
                "INSERT INTO audit_events(ts,tenant_id,actor,actor_type,action,entity_type,entity_id,payload,prev_hash,hash)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (ts, tenant_id, actor, actor_type, action, entity_type, entity_id, json.dumps(payload or {}, default=str), prev, h))
            return cur.lastrowid

    def verify_audit_chain(self) -> dict:
        """Recompute the whole chain. Returns {ok, checked, first_bad_seq}."""
        prev = "0" * 64
        n = 0
        with self.lock:
            rows = self.db.execute("SELECT * FROM audit_events ORDER BY seq").fetchall()
        for r in rows:
            body = {"ts": r["ts"], "tenant_id": r["tenant_id"], "actor": r["actor"], "actor_type": r["actor_type"],
                    "action": r["action"], "entity_type": r["entity_type"], "entity_id": r["entity_id"],
                    "payload": json.loads(r["payload"] or "{}")}
            if r["prev_hash"] != prev or sha256_text(prev + canonical_json(body)) != r["hash"]:
                return {"ok": False, "checked": n, "first_bad_seq": r["seq"]}
            prev = r["hash"]
            n += 1
        return {"ok": True, "checked": n, "first_bad_seq": None}

    # ---- flags (kill switch etc.) -----------------------------------------
    def flag(self, name: str, default: str = "0") -> str:
        r = self.get("flags", "name", name)
        return r["value"] if r else default

    def set_flag(self, name: str, value: str, by: str) -> None:
        with self.lock:
            self.db.execute("INSERT INTO flags(name,value,updated_by,updated_at) VALUES(?,?,?,?) "
                            "ON CONFLICT(name) DO UPDATE SET value=excluded.value, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                            (name, value, by, iso(now())))

    def ensure_tenant(self, tenant_id: str, name: str, pack: str = "default") -> None:
        if not self.get("tenant", "tenant_id", tenant_id):
            self.insert("tenant", {"tenant_id": tenant_id, "name": name, "policy_pack": pack, "created_at": iso(now())})


def make_store(settings) -> "Store":
    """VRO_DATABASE_URL set -> PostgreSQL (pgvector); otherwise SQLite at VRO_DB_PATH."""
    if getattr(settings, "database_url", ""):
        from .store_pg import PgStore
        return PgStore(settings.database_url, rls=settings.pg_rls, embed_dim=settings.embed_dim, admin_dsn=settings.database_url_admin or None,
                       max_size=settings.pg_pool_max, schema=settings.pg_schema or None)
    return Store(settings.db_path)
