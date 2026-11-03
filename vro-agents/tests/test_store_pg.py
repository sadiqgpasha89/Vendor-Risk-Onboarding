"""Postgres store tests. Pure helpers always run. Database tests run only when VRO_TEST_DATABASE_URL is set, e.g.
   docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=pw pgvector/pgvector:pg16
   VRO_TEST_DATABASE_URL=postgresql://postgres:pw@localhost:5432/postgres make test
Each test class uses a throw-away schema that is dropped afterwards."""
import os
import unittest
import uuid

import numpy as np

from vro import store_pg
from vro.store_pg import q_ident, render_sql, translate_sql, vector_literal

URL = os.environ.get("VRO_TEST_DATABASE_URL")


class PureHelpers(unittest.TestCase):
    def test_translate_params(self):
        self.assertEqual(translate_sql("SELECT * FROM t WHERE a=? AND b LIKE 'x%'", True), "SELECT * FROM t WHERE a=%s AND b ILIKE 'x%%'")

    def test_translate_no_params_leaves_percent_alone(self):
        self.assertEqual(translate_sql("SELECT name FROM flags WHERE name LIKE 'kill:%'", False), "SELECT name FROM flags WHERE name ILIKE 'kill:%'")

    def test_group_concat(self):
        self.assertEqual(translate_sql("SELECT GROUP_CONCAT(gate) FROM g", False), "SELECT string_agg(gate::text, ',') FROM g")

    def test_identifier_quoting_rejects_injection(self):
        self.assertEqual(q_ident("user"), '"user"')
        for bad in ('a"b', "a;drop", "1abc", "a b", ""):
            with self.assertRaises(ValueError):
                q_ident(bad)

    def test_vector_literal(self):
        v = np.array([0.5, -1.0, 0.25], dtype=np.float32)
        self.assertEqual(vector_literal(v.tobytes(), 3), "[0.5,-1,0.25]")
        with self.assertRaises(ValueError):
            vector_literal(v.tobytes(), 4)

    def test_render_sql(self):
        out = render_sql("ALTER TABLE x ADD c vector(:embed_dim); GRANT USAGE ON SCHEMA :schema TO r;", schema="vro_t", embed_dim=768)
        self.assertIn("vector(768)", out)
        self.assertIn('SCHEMA "vro_t"', out)

    def test_migrations_are_ordered_and_parametrised(self):
        files = sorted(p.name for p in store_pg.MIGRATIONS.glob("*.sql"))
        self.assertEqual(files, ["0001_init.sql", "0002_pgvector_fts.sql", "0003_rls.sql"])
        self.assertIn(":embed_dim", (store_pg.MIGRATIONS / "0002_pgvector_fts.sql").read_text())

    def test_schema_covers_every_sqlite_table(self):
        import re
        from vro.store import SCHEMA
        lite = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", SCHEMA))
        pg = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", "".join(p.read_text() for p in store_pg.MIGRATIONS.glob("*.sql"))))
        self.assertEqual(lite - pg, set())

    def test_every_sqlite_column_exists_in_pg_schema(self):
        import re
        from vro.store import SCHEMA
        pgsql = (store_pg.MIGRATIONS / "0001_init.sql").read_text()
        for tbl, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)\((.*?)\);", SCHEMA, re.S):
            m = re.search(rf"CREATE TABLE IF NOT EXISTS {tbl}\((.*?)\);", pgsql, re.S)
            self.assertIsNotNone(m, tbl)
            for col in re.findall(r"(?:^|,)\s*(\w+)\s+(?:TEXT|INTEGER|REAL|BLOB)", body):
                self.assertRegex(m.group(1), rf'(?<![\w"]){col}(?![\w])|"{col}"', f"{tbl}.{col}")

    def test_make_store_defaults_to_sqlite(self):
        from vro.config import Settings
        from vro.store import Store, make_store
        self.assertIsInstance(make_store(Settings(db_path=":memory:", database_url="")), Store)


@unittest.skipUnless(URL and store_pg.psycopg, "set VRO_TEST_DATABASE_URL (and install psycopg) to run Postgres tests")
class PgConformance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = "vro_t_" + uuid.uuid4().hex[:8]
        cls.st = store_pg.PgStore(URL, schema=cls.schema, embed_dim=8)

    @classmethod
    def tearDownClass(cls):
        cls.st.drop_schema()
        cls.st.close()

    def test_roundtrip_json_and_types(self):
        st = self.st
        st.ensure_tenant("t1", "T1")
        st.insert("cases", {"case_id": "c1", "tenant_id": "t1", "state": "NEW", "intake": {"a": [1, 2], "b": "x"}, "emergency": True, "created_at": "2026-01-01"})
        c = st.get("cases", "case_id", "c1")
        self.assertEqual(c["intake"], {"a": [1, 2], "b": "x"})
        self.assertEqual(c["emergency"], 1)
        st.update("cases", "case_id", "c1", {"state": "SCREENING", "context": {"k": "v"}})
        self.assertEqual(st.one("SELECT state, context FROM cases WHERE case_id=?", ("c1",))["context"], {"k": "v"})

    def test_reserved_column_and_like(self):
        st = self.st
        st.insert("feedback", {"feedback_id": "f1", "tenant_id": "t1", "kind": "k", "user": "alice", "created_at": "x"})
        self.assertEqual(st.get("feedback", "feedback_id", "f1")["user"], "alice")
        st.set_flag("kill:A4", "1", "u")
        self.assertEqual([r["name"] for r in st.query("SELECT name FROM flags WHERE name LIKE 'kill:%' AND value='1'")], ["kill:A4"])

    def test_audit_chain_and_append_only(self):
        st = self.st
        for i in range(5):
            st.audit("t1", "u", "human", "A", "case", "c1", {"i": i, "f": 1.0})
        self.assertTrue(st.verify_audit_chain()["ok"])
        with self.assertRaises(store_pg.psycopg.Error):
            st.execute("UPDATE audit_events SET actor='x' WHERE seq=1")
        with self.assertRaises(store_pg.psycopg.Error):
            st.execute("DELETE FROM audit_events")

    def test_concurrent_audit_appends_do_not_fork_chain(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(lambda i: self.st.audit("t1", f"u{i}", "human", "A", "case", "c", {"i": i}), range(40)))
        self.assertTrue(self.st.verify_audit_chain()["ok"])

    def test_tx_rolls_back(self):
        st = self.st
        with self.assertRaises(RuntimeError):
            with st.tx():
                st.insert("flags", {"name": "tmp", "value": "1", "updated_by": "u", "updated_at": "x"})
                raise RuntimeError("boom")
        self.assertIsNone(st.get("flags", "name", "tmp"))

    def test_hybrid_candidates(self):
        from vro.retrieval import HashingEmbedder
        emb = HashingEmbedder(8)
        st = self.st
        st.insert("documents", {"doc_id": "d1", "tenant_id": "t1", "vendor_id": "v1", "doc_type": "contract", "sha256": "s", "quarantine_status": "ACCEPTED"})
        texts = ["the vendor grants the bank a right to audit", "payment terms net thirty days", "exit assistance on termination"]
        for i, (t, v) in enumerate(zip(texts, emb.embed(texts))):
            st.insert("doc_chunks", {"chunk_id": f"k{i}", "tenant_id": "t1", "doc_id": "d1", "vendor_id": "v1", "text": t, "level": 0, "strategy": "x",
                                     "embedding": v.astype(np.float32).tobytes(), "meta": {}})
        rows = st.candidate_rows("t1", "v1", "right to audit", emb.embed(["right to audit"])[0], None, None, False)
        self.assertIn("k0", {r["chunk_id"] for r in rows})
        self.assertEqual(bytes(rows[0]["embedding"]).__len__(), 8 * 4)


@unittest.skipUnless(URL and store_pg.psycopg, "set VRO_TEST_DATABASE_URL to run")
class PgEndToEnd(unittest.TestCase):
    def test_clean_scenario_on_postgres(self):
        from evals.harness import drive
        from evals.runner import FROZEN
        from vro.agents.services import Services
        from vro.config import Settings
        from vro.util import set_now
        from vro.workflow import Workflow
        set_now(FROZEN)
        schema = "vro_e2e_" + uuid.uuid4().hex[:8]
        st = store_pg.PgStore(URL, schema=schema, embed_dim=512)
        try:
            svc = Services(Settings(llm_provider="rules", app_env="test"), store=st)
            r = drive(svc, Workflow(svc), "clean_t2")
            self.assertEqual(r["state"], "MONITORING")
            self.assertTrue(st.verify_audit_chain()["ok"])
        finally:
            set_now(None)
            st.drop_schema()
            st.close()


if __name__ == "__main__":
    unittest.main()
