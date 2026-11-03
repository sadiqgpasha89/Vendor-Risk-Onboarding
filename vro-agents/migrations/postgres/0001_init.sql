-- Core schema (PostgreSQL 14+). Mirrors the SQLite schema in vro/store.py with real types:
--   JSON columns -> JSONB, embeddings -> BYTEA (+ pgvector column added in 0002).
-- Timestamps stay ISO-8601 TEXT on purpose: the application compares them as strings; migrate to timestamptz as a separate, tested change.
CREATE TABLE IF NOT EXISTS tenant(tenant_id TEXT PRIMARY KEY, name TEXT, policy_pack TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS vendor(vendor_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, legal_name TEXT, trade_names JSONB,
  country_iso2 TEXT, reg_number TEXT, lei TEXT, website TEXT, status TEXT, tier INTEGER, created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_vendor_tenant ON vendor(tenant_id);
CREATE TABLE IF NOT EXISTS ownership_edge(edge_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT, child_name TEXT,
  parent_name TEXT, pct DOUBLE PRECISION, is_person INTEGER, country_iso2 TEXT, source TEXT, as_of TEXT);
CREATE INDEX IF NOT EXISTS ix_edge_case ON ownership_edge(case_id);
CREATE TABLE IF NOT EXISTS cases(case_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, vendor_id TEXT, requester_id TEXT,
  state TEXT NOT NULL, intake JSONB, proposed_tier INTEGER, final_tier INTEGER, jurisdictions JSONB, emergency INTEGER,
  sla_due_at TEXT, preparer_id TEXT, context JSONB, hold_reason TEXT, conditional_expires TEXT, created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_cases_tenant ON cases(tenant_id, state);
CREATE TABLE IF NOT EXISTS documents(doc_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT, vendor_id TEXT, doc_type TEXT,
  filename TEXT, mime TEXT, sha256 TEXT, size INTEGER, quarantine_status TEXT, hidden_text_flag INTEGER,
  injection_flags JSONB, page_count INTEGER, period_start TEXT, period_end TEXT, valid_until TEXT, supersedes_doc_id TEXT,
  uploaded_by TEXT, uploaded_at TEXT, raw_text TEXT, clean_text TEXT, language TEXT, version INTEGER, processed INTEGER DEFAULT 0,
  ocr_quality TEXT, parse_meta JSONB);
CREATE UNIQUE INDEX IF NOT EXISTS ux_doc_vendor_sha ON documents(vendor_id, sha256);
CREATE INDEX IF NOT EXISTS ix_doc_supersedes ON documents(supersedes_doc_id) WHERE supersedes_doc_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS doc_chunks(chunk_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, doc_id TEXT, vendor_id TEXT, parent_chunk_id TEXT,
  level INTEGER, strategy TEXT, section_path TEXT, page_from INTEGER, page_to INTEGER, text TEXT, token_count INTEGER,
  embedding BYTEA, meta JSONB, chunker_version TEXT);
CREATE INDEX IF NOT EXISTS ix_chunks_doc ON doc_chunks(doc_id);
CREATE INDEX IF NOT EXISTS ix_chunks_vendor ON doc_chunks(tenant_id, vendor_id);
CREATE TABLE IF NOT EXISTS claims(claim_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, vendor_id TEXT, case_id TEXT, subject TEXT,
  predicate TEXT, object JSONB, statement TEXT, status TEXT NOT NULL CHECK(status IN('TRUSTED','STALE','UNTRUSTED','REFUTED','SUPERSEDED')),
  confidence DOUBLE PRECISION, produced_by TEXT, prompt_version TEXT, version INTEGER, policy_version TEXT, valid_until TEXT,
  created_at TEXT, last_verified_at TEXT, stale_reason TEXT);
CREATE INDEX IF NOT EXISTS ix_claims_vendor ON claims(tenant_id, vendor_id, status);
CREATE TABLE IF NOT EXISTS claim_evidence(evidence_id TEXT PRIMARY KEY, claim_id TEXT NOT NULL, source_type TEXT, doc_id TEXT,
  chunk_id TEXT, page INTEGER, locator TEXT, quote TEXT, quote_hash TEXT, source_sha256 TEXT, source_version TEXT,
  retrieved_at TEXT, stance TEXT);
CREATE INDEX IF NOT EXISTS ix_ev_claim ON claim_evidence(claim_id);
CREATE TABLE IF NOT EXISTS claim_versions(claim_id TEXT, version INTEGER, statement TEXT, status TEXT, changed_by TEXT,
  change_reason TEXT, changed_at TEXT, PRIMARY KEY(claim_id, version, changed_at));
CREATE TABLE IF NOT EXISTS screening_results(screening_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT, subject_name TEXT,
  subject_role TEXT, list_name TEXT, list_version TEXT, match_entity_id TEXT, match_name TEXT, score DOUBLE PRECISION, features JSONB,
  auto_disposition TEXT, recommendation TEXT, explanation TEXT, human_disposition TEXT, dispositioned_by TEXT, rationale TEXT,
  created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_screen_case ON screening_results(case_id);
CREATE TABLE IF NOT EXISTS assessments(assessment_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT, scoring_version TEXT,
  inherent JSONB, control_effectiveness JSONB, residual JSONB, tier INTEGER, overrides JSONB, narrative TEXT, created_at TEXT,
  rowid BIGINT GENERATED ALWAYS AS IDENTITY);          -- 'rowid' keeps ORDER BY created_at DESC, rowid DESC working unchanged
CREATE INDEX IF NOT EXISTS ix_assess_case ON assessments(case_id, created_at);
CREATE TABLE IF NOT EXISTS findings(finding_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT, domain TEXT, severity TEXT,
  title TEXT, description TEXT, claim_ids JSONB, regulation_refs JSONB, remediation TEXT, status TEXT, owner TEXT, due_date TEXT,
  rule_id TEXT, disputed INTEGER DEFAULT 0, disputed_by TEXT, disputed_reason TEXT, disposition TEXT, disposition_by TEXT,
  exception_expires TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_findings_case ON findings(case_id, status);
CREATE TABLE IF NOT EXISTS questions(question_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT, to_role TEXT, text TEXT,
  why TEXT, blocking INTEGER, options JSONB, status TEXT, answer TEXT, answered_by TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS approvals(approval_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT, gate TEXT, approver_id TEXT,
  decision TEXT, conditions JSONB, rationale TEXT, decided_at TEXT);
CREATE INDEX IF NOT EXISTS ix_approvals_case ON approvals(case_id);
CREATE TABLE IF NOT EXISTS gate_tasks(task_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT, gate TEXT, status TEXT,
  role_required JSONB, created_at TEXT, due_at TEXT, payload JSONB);
CREATE INDEX IF NOT EXISTS ix_gate_case ON gate_tasks(case_id, status);
CREATE TABLE IF NOT EXISTS agent_runs(run_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT, agent TEXT, model TEXT,
  prompt_version TEXT, status TEXT, idempotency_key TEXT UNIQUE, input_hash TEXT, output JSONB, tokens_in INTEGER,
  tokens_out INTEGER, cost_usd DOUBLE PRECISION, latency_ms INTEGER, trace_id TEXT, started_at TEXT);
CREATE TABLE IF NOT EXISTS tool_calls(call_id TEXT PRIMARY KEY, run_id TEXT, tool TEXT, args_redacted JSONB, result_hash TEXT,
  status TEXT, latency_ms INTEGER, started_at TEXT);
-- Audit log: global hash chain, payload kept as exact TEXT so hashes are reproducible byte for byte.
CREATE TABLE IF NOT EXISTS audit_events(seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, ts TEXT, tenant_id TEXT, actor TEXT,
  actor_type TEXT, action TEXT, entity_type TEXT, entity_id TEXT, payload TEXT, prev_hash TEXT, hash TEXT);
CREATE INDEX IF NOT EXISTS ix_audit_entity ON audit_events(entity_id);
CREATE INDEX IF NOT EXISTS ix_audit_tenant ON audit_events(tenant_id, seq);
CREATE OR REPLACE FUNCTION audit_events_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'audit_events is append-only'; END $$;
DROP TRIGGER IF EXISTS audit_no_update ON audit_events;
CREATE TRIGGER audit_no_update BEFORE UPDATE OR DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION audit_events_immutable();
DROP TRIGGER IF EXISTS audit_no_truncate ON audit_events;
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_events FOR EACH STATEMENT EXECUTE FUNCTION audit_events_immutable();
CREATE TABLE IF NOT EXISTS nonces(source TEXT, nonce TEXT, ts TEXT, PRIMARY KEY(source, nonce));
CREATE TABLE IF NOT EXISTS idempotency(key TEXT PRIMARY KEY, tenant_id TEXT, response JSONB, created_at TEXT);
CREATE TABLE IF NOT EXISTS flags(name TEXT PRIMARY KEY, value TEXT, updated_by TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS drafts(draft_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT, kind TEXT, body TEXT,
  status TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS feedback(feedback_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT, kind TEXT, ref TEXT,
  note TEXT, "user" TEXT, created_at TEXT);                     -- "user" is reserved in PostgreSQL: always quoted
CREATE TABLE IF NOT EXISTS policy_activations(activation_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, pack TEXT, status TEXT,
  requested_by TEXT, approved_by TEXT, eval_passed INTEGER, created_at TEXT, decided_at TEXT);
CREATE TABLE IF NOT EXISTS list_versions(list_name TEXT PRIMARY KEY, version TEXT, loaded_at TEXT, entity_count INTEGER);
-- Background jobs (async "advance" so slow model calls do not hold an HTTP request open).
CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT, kind TEXT, status TEXT, requested_by TEXT,
  result JSONB, error TEXT, created_at TEXT, started_at TEXT, finished_at TEXT);
CREATE INDEX IF NOT EXISTS ix_jobs_case ON jobs(case_id, status);
