# ADR-0010 Async jobs and per-case locks

Status: accepted

## Context
Advance can run for minutes and must not block the event loop or race.

## Decision
Handlers run in a threadpool; advance is a job (202); per-case advisory locks; orphan reaping.

## Consequences
Move to a durable queue/Temporal at scale (see ADR-0003).
