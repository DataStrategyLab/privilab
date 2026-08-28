# ADR-008: Preview and deployment

- Status: Accepted
- Decision owner: Andrew

## Decision

P0 supports a localhost preview and local container only. Hosted deployment is
not approved.

## Consequences

The preview binds to `127.0.0.1` and displays a synthetic/reference-demo
placeholder. The Dockerfile is for local verification and introduces no hosted
deployment configuration.
