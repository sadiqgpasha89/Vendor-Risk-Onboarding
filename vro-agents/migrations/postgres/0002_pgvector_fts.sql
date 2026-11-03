-- Vector + full-text search for hybrid retrieval. Requires the pgvector extension (pgvector/pgvector Docker image, or
-- `CREATE EXTENSION vector` by a superuser / on managed Postgres: Cloud SQL, RDS, Azure, Supabase all offer it).
-- :embed_dim is substituted by the migration runner (VRO_EMBED_DIM). Changing the embedding model with a different dimension
-- needs a NEW migration that re-creates `vec` and re-indexes documents; never edit this file after it has been applied.
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE doc_chunks ADD COLUMN IF NOT EXISTS vec vector(:embed_dim);
ALTER TABLE doc_chunks ADD COLUMN IF NOT EXISTS tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(text, ''))) STORED;
CREATE INDEX IF NOT EXISTS ix_chunks_tsv ON doc_chunks USING gin(tsv);
-- Approximate nearest neighbour. Per-vendor corpora are small, so the btree filter on (tenant_id, vendor_id) usually wins; the HNSW index
-- serves portfolio-wide search. With pgvector >= 0.8 also `SET hnsw.iterative_scan = relaxed_order` for filtered ANN queries.
CREATE INDEX IF NOT EXISTS ix_chunks_vec ON doc_chunks USING hnsw (vec vector_cosine_ops);
