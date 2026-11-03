# ADR-0001: SQLite stands in for Postgres (+pgvector)
Status: accepted (environment-driven deviation)
Context: PyPI/npm and Docker were unavailable while building. The store is a thin layer (`vro/store.py`) with plain SQL and JSON columns.
Decision: Use SQLite (WAL) with SQL triggers that block UPDATE/DELETE on the audit table. Retrieval uses a hashing embedder + BM25 in-process.
Consequences: Single-node only. Production must port DDL to Postgres (row-level security for tenant isolation, pgvector for embeddings). Not exercised here.
