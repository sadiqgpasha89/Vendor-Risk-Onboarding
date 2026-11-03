# ADR-0009 Token-bucket rate limiting

Status: accepted

## Context
Uploads and writes are expensive; credential stuffing possible.

## Decision
Per-principal token buckets by class plus per-IP auth-failure throttle; optional Redis for shared state.

## Consequences
In-process limits are per replica.
