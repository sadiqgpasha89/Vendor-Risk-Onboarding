# ADR-0013 Sandboxed PDF worker

Status: accepted

## Context
PDF parsers and OCR are a classic attack surface.

## Decision
Run parsing in a rlimit-ed, timeout-bound subprocess with clean env; never execute active content; flag it.

## Consequences
Subprocess startup cost; stronger isolation (gVisor) recommended.
