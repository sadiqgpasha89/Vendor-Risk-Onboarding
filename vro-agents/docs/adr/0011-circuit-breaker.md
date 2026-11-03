# ADR-0011 Provider circuit breaker

Status: accepted

## Context
A failing LLM should not stall every request.

## Decision
Breaker per provider counting retryable errors only; fall back to rules unless disabled.

## Consequences
Fallback can mask failures; evals disable it.
