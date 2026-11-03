# ADR-0008 OIDC bearer auth

Status: accepted

## Context
Dev auth is unsafe in production.

## Decision
Validate RS256/ES256 JWTs with PyJWT against the IdP JWKS; roles/tenant from claims; refuse to start with dev auth in prod.

## Consequences
Depends on IdP claim mapping; tested with local keys only.
