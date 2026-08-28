# ADR-001: Application topology

- Status: Accepted
- Decision owner: Andrew

## Decision

PriviLAB P0 is a Python 3.13 modular monolith using FastAPI, Jinja, and minimal
browser JavaScript. Domain, application, adapter, evaluation, and web boundaries
remain explicit inside one repository and one deployable application.

## Consequences

Another application framework, distributed-service topology, or database class
requires a new ADR and Andrew's approval. DSL-105 scaffolds boundaries without
implementing later product behavior.
