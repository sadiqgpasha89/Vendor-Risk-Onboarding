-- Row-level security: tenant isolation enforced by the database, not only by application WHERE clauses. OPT-IN (VRO_PG_RLS=1).
-- The application role (vro_app) is NOT the table owner, so policies apply to it. Every transaction sets
--   SELECT set_config('app.tenant_id', '<tenant>', true)
-- (PgStore does this from the request's tenant scope). No setting => no rows visible: it fails closed.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'vro_app')    THEN CREATE ROLE vro_app NOLOGIN; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'vro_system') THEN CREATE ROLE vro_system NOLOGIN BYPASSRLS; END IF;
END $$;
GRANT USAGE ON SCHEMA :schema TO vro_app, vro_system;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA :schema TO vro_app, vro_system;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM vro_app, vro_system;     -- append-only, also at the privilege level
GRANT USAGE ON ALL SEQUENCES IN SCHEMA :schema TO vro_app, vro_system;

DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['vendor','ownership_edge','cases','documents','doc_chunks','claims','screening_results','assessments','findings',
                           'questions','approvals','gate_tasks','agent_runs','drafts','feedback','policy_activations','idempotency','jobs']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
    EXECUTE format($p$CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_setting('app.tenant_id', true))
                      WITH CHECK (tenant_id = current_setting('app.tenant_id', true))$p$, t);
  END LOOP;
END $$;
ALTER TABLE tenant ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON tenant;
CREATE POLICY tenant_isolation ON tenant USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
-- tables that carry no tenant_id inherit isolation through their parent
ALTER TABLE claim_evidence ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON claim_evidence;
CREATE POLICY tenant_isolation ON claim_evidence USING (claim_id IN (SELECT claim_id FROM claims)) WITH CHECK (claim_id IN (SELECT claim_id FROM claims));
ALTER TABLE claim_versions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON claim_versions;
CREATE POLICY tenant_isolation ON claim_versions USING (claim_id IN (SELECT claim_id FROM claims)) WITH CHECK (claim_id IN (SELECT claim_id FROM claims));
ALTER TABLE tool_calls ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON tool_calls;
CREATE POLICY tenant_isolation ON tool_calls USING (run_id IN (SELECT run_id FROM agent_runs)) WITH CHECK (run_id IN (SELECT run_id FROM agent_runs));
-- audit: anyone may append; each tenant reads only its own rows (NULL-tenant system events are visible to nobody but vro_system)
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS audit_insert ON audit_events;
CREATE POLICY audit_insert ON audit_events FOR INSERT WITH CHECK (true);
DROP POLICY IF EXISTS audit_read ON audit_events;
CREATE POLICY audit_read ON audit_events FOR SELECT USING (tenant_id = current_setting('app.tenant_id', true));
-- The hash chain is GLOBAL, so appending needs the previous hash across tenants. SECURITY DEFINER exposes exactly that one value.
CREATE OR REPLACE FUNCTION vro_audit_tail() RETURNS text LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, :schema AS
$$ SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1 $$;
REVOKE ALL ON FUNCTION vro_audit_tail() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION vro_audit_tail() TO vro_app, vro_system;
CREATE OR REPLACE FUNCTION vro_audit_all() RETURNS SETOF audit_events LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, :schema AS
$$ SELECT * FROM audit_events ORDER BY seq $$;
REVOKE ALL ON FUNCTION vro_audit_all() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION vro_audit_all() TO vro_system;                         -- chain verification runs as the system role only
