# Capabilities and limits

## Implemented in this checkout

PriviLAB is a Python modular monolith with a local server-rendered preview.
`RunService` owns permission, scoped retrieval, provider execution and terminal
provenance. `RunReviewService` adds deterministic evaluation and explicit review.
SQLite/FTS5 performs application-scoped retrieval; SQLite stores metadata.

The fixture provider uses versioned fixed outputs. An OpenAI adapter exists behind
the provider boundary, configured for `gpt-5.6-terra`; offline fake-SDK tests cover
its request and failure behavior. A local smoke implementation records reported
usage, provider-call latency and cost only when adequate applicable pricing/
billing evidence exists in offline mocked tests. The default live SDK client is
disabled before credentials or HTTP construction, pending native trust qualification. Missing cost is unavailable, not measured zero. Hosted
live-eval also remains blocked; retained local opt-in code does not override the hold.

## Local web routes

| Route | Purpose |
| --- | --- |
| GET `/` | Synthetic scenario selector |
| POST `/runs` | Execute an explicitly selected fixture scenario |
| GET `/runs` | Newest 25 finalized metadata records |
| GET `/runs/{run_id}` | Reopen metadata without generation/retrieval/evaluation replay |
| POST `/runs/{run_id}/review` | One allowed immutable synthetic review action |

No production authentication or DMS authorization is implemented. Request input
is restricted to listed choices, and the UI cannot select a corpus/database path.
An application permission scope filters source content before model context.

## What the gates mean

Permission ALLOW, CONDITIONAL, BLOCK and UNKNOWN are distinct from Legal AI
Readiness G1/G2/G3. Missing context and unresolved conditions fail closed.
The four critical evaluation criteria check source membership, citation resolution,
permission boundary and provenance completeness. These structural checks do not
prove that a cited source supports a substantive legal proposition.

Generated critical BLOCK disables approval. Reject/Request revision can still be
recorded on generated blocked drafts. Stopped runs are not reviewable. Evaluation
or evidence persistence failure does not manufacture PASS/review eligibility.
Synthetic-local-reviewer is a fixed UI identity, not authenticated legal/client
release authority. Request revision creates no revision lineage or drafting flow.

## Retention

Run, permission/configuration, source/chunk identifiers, provider identity,
evaluation results and immutable review metadata support traceability. Generated
answer, prompt/task/query and source bodies, raw provider requests/responses,
credentials and raw exceptions are not retained in run history. The retrieval
index is transient. Live telemetry retains its separate typed metadata and
applicable pricing snapshot; that does not establish provider-side retention.

## Planned or unestablished

DMS/enterprise identity integrations, hosted runtime, additional providers,
open-weight fine-tuning, generalized benchmark comparisons and production
hardening remain roadmap work. There are no model-controlled tools, autonomous
agent framework or runtime MCP dependencies. User-level Linear engineering
integration is not an application capability.

No claim of legal adequacy, privilege, OCG/client compliance, ZDR, confidentiality,
security certification, zero hallucinations, savings, vendor endorsement or
production fitness follows from the code or deterministic checks. The six domain
tasks remain internal-only pending qualified review. See the
[dated release status](release-status.md).
