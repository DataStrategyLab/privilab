# P0 system architecture

## Status

Approved Gate 2/Gate 3 architecture for the controlled P0 reference demo.

## Topology

PriviLAB is a Python 3.13 modular monolith using FastAPI, Jinja templates, and
minimal browser JavaScript. Local SQLite with FTS5 is the approved persistence
and retrieval substrate when those later issues are implemented.

The package boundaries are:

- `domain`: typed business and permission contracts.
- `application`: orchestration such as the future RunService.
- `adapters`: model, retrieval, and storage implementations.
- `evals`: deterministic evaluation integration.
- `web`: server-rendered presentation.

DSL-105 implements only a static placeholder through the web boundary. Empty
packages make the topology visible without implementing later-issue behavior.

## Approved control sequence

The future runtime sequence is context, permission, authorization-scoped
retrieval, fixture generation, evaluation, provenance, and separate human
review. Authorization filtering occurs before source content can enter model
context. `BLOCK`, `UNKNOWN`, and unresolved `CONDITIONAL` outcomes fail closed.

## Provider sequence

DSL-114 completed and accepted the fixture-first prerequisite. DSL-115 implements
the ADR-003-approved OpenAIProvider for `gpt-5.6-terra` through the Responses API
and the sanctioned `RunService.from_openai` factory. It preserves the existing
provider, permission, retrieval, evaluation, review, and provenance contracts.
An adapter-specific immutable result/usage pair supplies the DSL-116 handoff;
DSL-115 adds no usage, latency, pricing, or cost persistence. Live smoke execution
belongs to DSL-116. Preview and CI remain offline and fixture-based. No runtime
autonomous-agent framework, model-controlled tools, or runtime MCP are approved.

## Execution environments

P0 supports localhost preview and a local container only. Hosted deployment is
not approved. `make ci` is the canonical secret-free, post-bootstrap
network-free verification contract.
