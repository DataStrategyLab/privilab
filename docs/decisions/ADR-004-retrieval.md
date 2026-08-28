# ADR-004: Retrieval

- Status: Accepted
- Decision owner: Andrew

## Decision

P0 retrieval uses local SQLite with FTS5. Authorization filtering happens before
source content enters model context.

## Consequences

External search, embeddings, vector databases, and DMS retrieval are out of
scope. DSL-105 reserves the adapter location but implements no retrieval.
