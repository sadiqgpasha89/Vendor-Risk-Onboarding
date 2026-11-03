# Postgres + pgvector

Untested against a live database in the authoring environment; pure helpers and schema parity are tested.

1. Use image `pgvector/pgvector:pg16`. Create DB and roles (`vro_app`, `vro_system`; see `migrations/postgres/0003_rls.sql`).
2. `.env`: `VRO_DATABASE_URL=postgresql://vro_app:...@host/vro`, `VRO_DATABASE_URL_ADMIN=...` (migrations), optional `VRO_PG_RLS=1`, `EMBED_PROVIDER` (ollama|google|openai) and `EMBED_DIM` (must match the model; changing it requires re-embedding and a new `vec` column).
3. Install extras: `pip install -e ".[prod]"`. Start the app: migrations apply automatically on first connect.
4. Migrate existing SQLite data: `python -m tools.migrate_sqlite_to_pg --sqlite data/vro.db --dsn "$VRO_DATABASE_URL_ADMIN"` (preserves audit rows and sequence, then verifies the chain).
5. Run gated tests: `VRO_TEST_DATABASE_URL=postgresql://... make test`.

Design notes: JSON columns are JSONB; timestamps stay TEXT (ISO) for parity; audit payload TEXT for byte-exact hashing; advisory lock serialises audit appends; append-only triggers; HNSW (cosine) + GIN FTS with hybrid candidate query.
