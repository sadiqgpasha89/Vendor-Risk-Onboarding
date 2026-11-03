# Security configuration

**Auth.** Production uses OIDC bearer tokens: set `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL` (optional), `OIDC_ALGS` (default RS256,ES256), claims `OIDC_ROLES_CLAIM`, `OIDC_TENANT_CLAIM`. Roles: analyst, approver, admin, auditor (see policy). `X-VRO-Role` selects among roles the token already holds. `VRO_DEV_AUTH=1` is rejected when `APP_ENV=prod` (the app refuses to start).

**Startup guard.** `production_problems()` lists unsafe settings (dev auth, no OIDC, wildcard hosts, SQLite in prod, hosted LLM without opt-in); `create_app()` raises.

**Rate limits.** `RATE_LIMIT_READ/WRITE/UPLOAD` per minute per principal, auth-failure throttle per IP. In-process by default; set `REDIS_URL` for cluster-wide limits.

**Database.** Use `VRO_DATABASE_URL` (app role `vro_app`, non-owner). With `VRO_PG_RLS=1` set up tenant RLS (migration 0003); migrations run with `VRO_DATABASE_URL_ADMIN`.

**Secrets.** Only via env/secret store; never in prompts or logs (`obs.scrub`). PDF worker gets a clean environment.

**Network.** Egress allow-list to the LLM host and IdP; NetworkPolicy provided. Terminate TLS at ingress; HSTS is sent in prod.

**Checklist.** [ ] OIDC tested with your IdP [ ] RLS tested with two tenants [ ] metrics not public [ ] TRUSTED_PROXIES set [ ] hosted LLM approved by DPO [ ] audit head anchored externally [ ] backups restored once.
