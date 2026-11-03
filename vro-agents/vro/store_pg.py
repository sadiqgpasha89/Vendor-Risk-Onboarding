"""PostgreSQL + pgvector store: drop-in for `vro.store.Store` (same public API), selected by VRO_DATABASE_URL.

    pip install "psycopg[binary]>=3.1" "psycopg-pool>=3.2"        # see pyproject [project.optional-dependencies].prod
    export VRO_DATABASE_URL=postgresql://vro_app:...@host:5432/vro
    python -m vro.cli serve                                         # migrations run on start (idempotent)

NOT RUN in the authoring environment (no Postgres, no psycopg). Pure-Python parts (SQL translation, DDL rendering, vector literal) are unit
tested; the database behaviour is covered by tests/test_store_pg.py, which runs when VRO_TEST_DATABASE_URL is set. Read docs/POSTGRES.md.

Design notes
 * Same SQL as the SQLite store: `?` placeholders and LIKE are translated; `rowid` exists as an identity column on `assessments`.
 * JSON columns are JSONB (psycopg adapts dict/list/str via Jsonb); everything else keeps the SQLite store's types so behaviour matches.
 * Identifiers are always quoted (the `feedback."user"` column is reserved in PostgreSQL).
 * Audit chain: appends take a transaction-level advisory lock so concurrent writers cannot fork the hash chain.
 * RLS (opt-in, VRO_PG_RLS=1): every transaction sets app.tenant_id from the request's tenant scope; no scope => no rows (fail closed).
 * Hybrid retrieval: `candidate_rows` asks Postgres for the union of top-N by cosine distance (pgvector HNSW) and top-N by ts_rank_cd (GIN);
   the existing Python RRF + rerank then runs on that small set.
"""
from __future__ import annotations

import contextvars
import json
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from . import store as _sqlite_store
from .store import JSON_COLS
from .util import canonical_json, iso, now, sha256_text

try:                                              # imported lazily so the rest of the system works without the driver
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
    from psycopg_pool import ConnectionPool
    _sqlite_store.DB_ERRORS = tuple(_sqlite_store.DB_ERRORS) + (psycopg.Error,)
except ImportError:                               # pragma: no cover
    psycopg = None                                # type: ignore[assignment]

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations" / "postgres"
_AUDIT_LOCK = 7340211
_MIGRATE_LOCK = 7340210
_TENANT: contextvars.ContextVar[str | None] = contextvars.ContextVar("vro_tenant", default=None)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ------------------------------------------------------------------------------------------ pure helpers (unit tested)
def translate_sql(sql: str, has_params: bool) -> str:
    """SQLite-flavoured SQL -> psycopg/PostgreSQL. `?` -> `%s`, literal `%` escaped, LIKE -> ILIKE (SQLite's LIKE is case-insensitive)."""
    s = re.sub(r"\bLIKE\b", "ILIKE", sql)
    s = re.sub(r"\bGROUP_CONCAT\(\s*([\w.]+)\s*\)", r"string_agg(\1::text, ',')", s)
    if has_params:
        s = s.replace("%", "%%").replace("?", "%s")
    return s


def q_ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"unsafe identifier: {name!r}")
    return '"' + name + '"'


def vector_literal(blob: bytes, dim: int) -> str:
    import numpy as np
    v = np.frombuffer(blob, dtype=np.float32)
    if len(v) != dim:
        raise ValueError(f"embedding has {len(v)} dims but the database column is vector({dim}); set VRO_EMBED_DIM and migrate")
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def render_sql(text: str, *, schema: str, embed_dim: int) -> str:
    return text.replace(":embed_dim", str(int(embed_dim))).replace(":schema", q_ident(schema))


def _enc(col: str, v: Any):
    if col in JSON_COLS:
        return None if v is None else Jsonb(v, dumps=lambda o: json.dumps(o, default=str))
    if isinstance(v, bool):
        return int(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _dec(row: dict | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k in list(d):
        if k in JSON_COLS and isinstance(d[k], str):      # TEXT columns that share a JSON column name (e.g. audit payload) decode like SQLite
            try:
                d[k] = json.loads(d[k])
            except (ValueError, TypeError):
                pass
        elif isinstance(d[k], memoryview):
            d[k] = bytes(d[k])
    return d


# ------------------------------------------------------------------------------------------ the store
class PgStore:
    is_postgres = True

    def __init__(self, dsn: str, *, schema: str | None = None, rls: bool = False, embed_dim: int = 512, min_size: int = 1, max_size: int = 10,
                 migrate: bool = True, admin_dsn: str | None = None):
        if psycopg is None:
            raise RuntimeError('PgStore needs the Postgres driver: pip install "psycopg[binary]>=3.1" "psycopg-pool>=3.2"')
        self.dsn, self.schema, self.rls, self.embed_dim = dsn, schema or "public", rls, embed_dim
        self.path = dsn.split("@")[-1]                                       # host/db only; never log credentials
        self._tl = threading.local()
        kwargs: dict[str, Any] = {"row_factory": dict_row}
        if schema:
            with psycopg.connect(dsn, autocommit=True) as c:
                c.execute(f"CREATE SCHEMA IF NOT EXISTS {q_ident(schema)}")
            kwargs["options"] = f"-c search_path={schema},public"
        self._kwargs = kwargs
        self.pool = ConnectionPool(dsn, min_size=min_size, max_size=max_size, kwargs=kwargs, open=True)
        self.admin_pool = ConnectionPool(admin_dsn, min_size=0, max_size=2, kwargs=kwargs, open=True) if admin_dsn else None
        if migrate:
            self.migrate()

    # ---- migrations ------------------------------------------------------------------------------------
    def migrate(self) -> list[str]:
        applied: list[str] = []
        pool = self.admin_pool or self.pool                                  # DDL needs the owner role
        with pool.connection() as c:
            c.execute("SELECT pg_advisory_lock(%s)", (_MIGRATE_LOCK,))
            try:
                c.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT)")
                done = {r["version"] for r in c.execute("SELECT version FROM schema_migrations").fetchall()}
                for f in sorted(MIGRATIONS.glob("*.sql")):
                    if f.name in done or (f.name.endswith("_rls.sql") and not self.rls):
                        continue
                    c.execute(render_sql(f.read_text(), schema=self.schema, embed_dim=self.embed_dim))
                    c.execute("INSERT INTO schema_migrations(version, applied_at) VALUES(%s,%s)", (f.name, iso(now())))
                    applied.append(f.name)
                c.commit()
            finally:
                c.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATE_LOCK,))
                c.commit()
        return applied

    # ---- tenant scope (RLS) ------------------------------------------------------------------------------
    @contextmanager
    def tenant_scope(self, tenant_id: str | None):
        tok = _TENANT.set(tenant_id)
        try:
            yield
        finally:
            _TENANT.reset(tok)

    def set_tenant(self, tenant_id: str | None) -> None:
        """Bind the CURRENT request context to a tenant. Contextvars are per-request (asyncio task / copied into the worker thread)."""
        _TENANT.set(tenant_id)

    def _scope(self, conn) -> None:
        if self.rls:
            conn.execute("SELECT set_config('app.tenant_id', %s, true)", (_TENANT.get() or "",))

    # ---- connection handling ------------------------------------------------------------------------------
    @contextmanager
    def _conn(self):
        c = getattr(self._tl, "conn", None)
        if c is not None:
            yield c
            return
        with self.pool.connection() as conn:                                # commits on success, rolls back on exception
            self._scope(conn)
            yield conn

    @contextmanager
    def tx(self):
        if getattr(self._tl, "conn", None) is not None:                     # re-entrant: join the outer transaction
            yield
            return
        with self.pool.connection() as conn:
            self._scope(conn)
            self._tl.conn = conn
            try:
                yield
            finally:
                self._tl.conn = None

    @contextmanager
    def advisory_lock(self, key: str):
        held = getattr(self._tl, "held", None)
        if held is None:
            held = self._tl.held = set()
        if key in held:                                    # re-entrant in this thread (a second pooled connection would self-deadlock)
            yield
            return
        with self.pool.connection() as c:
            c.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (key,))
            held.add(key)
            try:
                yield
            finally:
                held.discard(key)
                c.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (key,))
                c.commit()

    # ---- generic helpers (same contract as Store) ---------------------------------------------------------------
    def _run(self, sql: str, params: Iterable = ()):
        p = tuple(params)
        with self._conn() as c:
            cur = c.execute(translate_sql(sql, bool(p)), p if p else None)
            return cur.fetchall() if cur.description else []

    def insert(self, table: str, row: dict) -> None:
        cols = list(row)
        vals = [_enc(c, row[c]) for c in cols]
        marks = ["%s"] * len(cols)
        if table == "doc_chunks" and row.get("embedding") is not None:        # keep BYTEA for parity, add the pgvector column for ANN search
            cols.append("vec")
            vals.append(vector_literal(bytes(row["embedding"]), self.embed_dim))
            marks.append("%s::vector")
        with self._conn() as c:
            c.execute(f"INSERT INTO {q_ident(table)}({','.join(q_ident(x) for x in cols)}) VALUES({','.join(marks)})", vals)

    def update(self, table: str, key_col: str, key: Any, changes: dict) -> None:
        if not changes:
            return
        cols = list(changes)
        with self._conn() as c:
            c.execute(f"UPDATE {q_ident(table)} SET {','.join(q_ident(x) + '=%s' for x in cols)} WHERE {q_ident(key_col)}=%s",
                      [_enc(x, changes[x]) for x in cols] + [key])

    def get(self, table: str, key_col: str, key: Any) -> dict | None:
        rows = self._run(f"SELECT * FROM {q_ident(table)} WHERE {q_ident(key_col)}=?", (key,))
        return _dec(rows[0]) if rows else None

    def query(self, sql: str, params: Iterable = ()) -> list[dict]:
        return [_dec(r) for r in self._run(sql, params)]

    def one(self, sql: str, params: Iterable = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: Iterable = ()) -> None:
        self._run(sql, params)

    # ---- audit chain ----------------------------------------------------------------------------------------------
    def audit(self, tenant_id: str | None, actor: str, actor_type: str, action: str, entity_type: str,
              entity_id: str | None, payload: dict | None = None) -> int:
        with self.tx():
            c = self._tl.conn
            c.execute("SELECT pg_advisory_xact_lock(%s)", (_AUDIT_LOCK,))     # serialise appenders: the chain is global and must not fork
            last = c.execute("SELECT vro_audit_tail() AS hash" if self.rls else "SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
            prev = (last or {}).get("hash") or "0" * 64
            ts = iso(now())
            body = {"ts": ts, "tenant_id": tenant_id, "actor": actor, "actor_type": actor_type, "action": action,
                    "entity_type": entity_type, "entity_id": entity_id, "payload": payload or {}}
            h = sha256_text(prev + canonical_json(body))
            sql = ("INSERT INTO audit_events(ts,tenant_id,actor,actor_type,action,entity_type,entity_id,payload,prev_hash,hash) "
                   "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")
            args = (ts, tenant_id, actor, actor_type, action, entity_type, entity_id, json.dumps(payload or {}, default=str), prev, h)
            if self.rls:      # RETURNING would be filtered by the SELECT policy for system (NULL-tenant) events
                c.execute(sql, args)
                return int(c.execute("SELECT currval(pg_get_serial_sequence('audit_events','seq')) AS s").fetchone()["s"])
            return int(c.execute(sql + " RETURNING seq", args).fetchone()["seq"])

    def verify_audit_chain(self) -> dict:
        pool = self.admin_pool or self.pool
        with pool.connection() as c:
            rows = c.execute("SELECT * FROM vro_audit_all()" if self.rls else "SELECT * FROM audit_events ORDER BY seq").fetchall()
        prev, n = "0" * 64, 0
        for r in rows:
            body = {"ts": r["ts"], "tenant_id": r["tenant_id"], "actor": r["actor"], "actor_type": r["actor_type"], "action": r["action"],
                    "entity_type": r["entity_type"], "entity_id": r["entity_id"], "payload": json.loads(r["payload"] or "{}")}
            if r["prev_hash"] != prev or sha256_text(prev + canonical_json(body)) != r["hash"]:
                return {"ok": False, "checked": n, "first_bad_seq": r["seq"]}
            prev, n = r["hash"], n + 1
        return {"ok": True, "checked": n, "first_bad_seq": None}

    # ---- flags / tenants ---------------------------------------------------------------------------------------------
    def flag(self, name: str, default: str = "0") -> str:
        r = self.get("flags", "name", name)
        return r["value"] if r else default

    def set_flag(self, name: str, value: str, by: str) -> None:
        self.execute("INSERT INTO flags(name,value,updated_by,updated_at) VALUES(?,?,?,?) "
                     "ON CONFLICT(name) DO UPDATE SET value=excluded.value, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                     (name, value, by, iso(now())))

    def ensure_tenant(self, tenant_id: str, name: str, pack: str = "default") -> None:
        with self.tenant_scope(tenant_id):
            if not self.get("tenant", "tenant_id", tenant_id):
                self.insert("tenant", {"tenant_id": tenant_id, "name": name, "policy_pack": pack, "created_at": iso(now())})

    # ---- hybrid retrieval candidates (used by RetrievalIndex when present) -------------------------------------------------
    def candidate_rows(self, tenant_id: str, vendor_id: str, query: str, qvec, doc_types: list[str] | None, doc_ids: list[str] | None,
                       include_superseded: bool, n: int = 40) -> list[dict]:
        where, params = ["c.tenant_id=%s", "c.vendor_id=%s", "coalesce((c.meta->>'indexable')::boolean, true)"], [tenant_id, vendor_id]
        if not include_superseded:
            where.append("c.doc_id NOT IN (SELECT supersedes_doc_id FROM documents WHERE supersedes_doc_id IS NOT NULL)")
        if doc_types:
            where.append("d.doc_type = ANY(%s)"); params.append(list(doc_types))
        if doc_ids:
            where.append("c.doc_id = ANY(%s)"); params.append(list(doc_ids))
        vec = "[" + ",".join(f"{float(x):.7g}" for x in qvec) + "]"
        sql = f"""
          WITH base AS (SELECT c.chunk_id, c.vec, c.tsv FROM doc_chunks c JOIN documents d ON d.doc_id=c.doc_id WHERE {' AND '.join(where)}),
          dense AS (SELECT chunk_id FROM base ORDER BY vec <=> %s::vector LIMIT %s),
          lex AS (SELECT chunk_id FROM base, websearch_to_tsquery('english', %s) q WHERE tsv @@ q ORDER BY ts_rank_cd(tsv, q) DESC LIMIT %s)
          SELECT c.*, d.doc_type AS doc_type FROM doc_chunks c JOIN documents d ON d.doc_id=c.doc_id
          WHERE c.chunk_id IN (SELECT chunk_id FROM dense UNION SELECT chunk_id FROM lex)"""
        with self._conn() as c:
            rows = c.execute(sql, params + [vec, n, query, n]).fetchall()
        return [_dec(r) for r in rows]

    def close(self) -> None:
        self.pool.close()
        if self.admin_pool:
            self.admin_pool.close()

    def drop_schema(self) -> None:             # test helper
        with psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute(f"DROP SCHEMA IF EXISTS {q_ident(self.schema)} CASCADE")
