# ADR-0014 Pluggable embeddings

Status: accepted

## Context
Hash embeddings are not semantic.

## Decision
Ollama/Google/OpenAI embedders behind one interface; dimension is config.

## Consequences
Changing model needs re-embedding.
