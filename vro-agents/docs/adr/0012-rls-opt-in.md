# ADR-0012 Postgres RLS opt-in

Status: accepted

## Context
Defence in depth for tenant isolation.

## Decision
Tenant GUC + policies behind VRO_PG_RLS; SECURITY DEFINER audit functions.

## Consequences
Needs non-owner app role; untested here.
