# ADR-002: Runtime boundary

- Status: Accepted
- Decision owner: Andrew

## Decision

The runtime will not use an autonomous-agent framework, model-controlled tools,
or runtime MCP. Application code owns sequencing and control decisions.

## Consequences

Engineering integrations such as approved user-level Linear MCP are outside the
PriviLAB runtime and cannot authorize architecture or release actions.
