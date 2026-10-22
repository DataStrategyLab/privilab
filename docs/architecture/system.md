# System architecture

PriviLAB implements the accepted Python modular-monolith architecture. FastAPI
and Jinja render a local synthetic preview; SQLite/FTS5 supports scoped retrieval
and SQLite stores minimum provenance/evaluation/review metadata. This describes
current code, without changing the [accepted ADRs](../decisions/README.md).

## Components

```mermaid
flowchart TB
    UI["Browser: server-rendered fixture demo"] --> WEB["FastAPI / Jinja"]
    WEB --> REVIEW["RunReviewService"]
    REVIEW --> RUN["RunService"]
    RUN --> PERM["Permission policy + application-created AccessScope"]
    PERM --> RET["SQLite FTS5 authorization-scoped retrieval"]
    RET --> MODEL["ModelProvider contract"]
    MODEL --> FIX["FixtureModelProvider"]
    MODEL --> OAI["OpenAI adapter: opt-in local live smoke"]
    RUN --> STORE["SQLiteProvenanceStore"]
    REVIEW --> EVAL["Deterministic critical evaluator"]
    EVAL --> STORE
    REVIEW --> STORE
    RET --> CORPUS["Registered synthetic corpus"]
```

| Package | Responsibility |
| --- | --- |
| `domain` | Typed context, permission, source/retrieval and research contracts |
| `application` | Permission policy, authorized scope, RunService, RunReviewService and telemetry |
| `adapters/retrieval` | SQLite/FTS5 filtering and stable source/chunk identity |
| `adapters/models` | Versioned fixture outputs and approved OpenAI adapter |
| `adapters/storage` | Typed immutable provenance, evaluation, review and telemetry persistence |
| `evals` | Criteria/contracts, deterministic smoke/golden runners and local live-smoke entry |
| `web` | Server-rendered scenario/result/history presentation and local assets |

## Request sequence

```mermaid
sequenceDiagram
    participant U as Browser
    participant V as RunReviewService
    participant R as RunService
    participant P as Permission policy
    participant T as Scoped retrieval
    participant M as Fixture provider
    participant S as SQLite metadata
    U->>V: Explicit synthetic scenario
    V->>R: Trusted task/context composition
    R->>P: Evaluate synthetic context
    alt BLOCK, UNKNOWN or unresolved CONDITIONAL
        P-->>R: Stop decision
        R->>S: Terminal stopped provenance
    else Allowed progression
        P-->>R: Application-created authorized scope
        R->>T: Retrieve within scope
        T-->>R: Authorized chunks only
        R->>M: Task plus authorized context
        M-->>R: Structured transient fixture result
        R->>S: Terminal run metadata
    end
    R-->>V: Outcome plus provenance
    V->>V: Deterministic evaluation
    V->>S: Evaluation metadata
    V-->>U: Result or safe stop, gate and review availability
    U->>V: Separate synthetic decision if allowed
    V->>S: One immutable decision
```

Terminal run provenance exists before evaluation; evaluation failure does not
remove that history or imply eligibility. Stopped runs remain NOT REVIEWABLE.
Generated critical BLOCK disables approval, while negative review actions remain
available. A local review decision does not authorize a repository/product release.

## History and providers

History reads stored metadata; it does not repeat retrieval, generation or
evaluation and retains no answer/task/query/source bodies. The retrieval index
is transient. Stored configuration/hash and source/chunk IDs identify the run,
without claiming that metadata can replay the complete answer.

The fixture path is the default preview/CI. The OpenAI adapter uses the sanctioned
RunService composition and configured model alias, preserving permission before
model context. Its live smoke is separately gated and records typed usage/latency/
conditional-cost evidence. No mutable last-call state or model-controlled tools
are introduced. See [live-smoke details](live-eval.md).

## Environments and boundaries

The implemented native source preview is local and uses public/synthetic inputs;
its uv/Python bootstrap qualification remains pending.
[ADR-008](../decisions/ADR-008-preview-deployment.md) permits localhost preview and
local containers as the architectural scope. The current container setup is on a
temporary security-qualification hold for this Developer Preview; the hold does
not supersede ADR-008's architectural decision. During the hold, the Dockerfile
remains an engineering reference rather than a recommended public setup.
Existing executable Makefile targets do not lift the hold or authorize operation.
See [local setup qualification](../release-status.md#local-setup-qualification)
for current restrictions. Historical container observations retain their original
scope; no deployment behavior changes are introduced here.

No hosted runtime, production identity/DMS integration, autonomous framework or
runtime MCP is part of this architecture. Post-bootstrap `make ci` is offline and
secret-free. [Trust boundaries](trust-boundaries.md) explain the control/authority
separation.
