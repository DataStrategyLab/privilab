# Decision log

## 2026-08-27 — Linear MCP engineering exception

2026-08-27: Approved Linear MCP for Codex engineering/project-management access only. This supersedes the Gate 3 bootstrap assumption of no MCP for engineering sessions. Linear MCP is not part of the PriviLAB runtime, may not access client/DMS data or deployment credentials, and does not authorize architecture changes or autonomous merge/release actions. Approved by Andrew.

This exception does not add repository MCP configuration, a runtime dependency,
or product functionality.

## 2026-09-12 — Task-specific Codex implementation model routing

Normal Codex implementation model selection is task-specific. The human task
owner selects the supported model and reasoning effort appropriate to each task:
routine work may use a balanced model, while complex, security-sensitive, or
high-judgment work may use a higher-capability model. Dedicated Codex code
review remains pinned to Sol through `review_model`. This changes development
tooling policy, not PriviLAB runtime model architecture.

## 2026-09-28 — GPT-6 Astra for dedicated Codex review

Dedicated Codex `/review` now uses `gpt-6-astra` through
`.codex/config.toml`.

This supersedes only the review-model portion of the 2026-09-12
task-specific Codex implementation model-routing decision. Normal Codex
implementation model and reasoning-effort selection remain task-specific
and are not repository-pinned.

The change affects development tooling only. It does not change PriviLAB
runtime model/provider architecture, application behavior, agent autonomy,
sandboxing, network access, web-search policy, multi-agent policy, human
review requirements, or merge/release authority.

## 2026-09-28 — DSL-115 provider and DSL-116 telemetry allocation

Andrew approved the DSL-115 implementation
plan after DSL-114 satisfied ADR-003's fixture-first prerequisite. DSL-115 owns
the official OpenAI Responses adapter for exactly `gpt-5.6-terra`, governed
composition, and an immutable execution-bound `OpenAIGeneration` containing the
`ResearchResult` and available `OpenAIUsage` counts. `generate_with_usage` is an
adapter-specific extension; `ModelProvider.generate` and `RunOutcome` are unchanged.
DSL-116 owns live smoke execution and usage/latency/pricing/cost integration and
persistence. Neither last-call state nor telemetry persistence belongs to DSL-115.

The approved SDK dependency is `openai>=3.19.2,<4`, initially locked to `3.19.2`
with its mandatory dependency closure and no extras. The SDK's raw response
wrapper still invokes Responses `create`; wire usage is checked before SDK
numeric coercion, then discarded after producing immutable counts.

Reversible P0 defaults are a 30-second SDK transport timeout (1–120 seconds),
two application retries (0–2), 0.5/1-second backoff, and a five-second maximum
retry delay (1–5 seconds). SDK retries are disabled. Valid server delays are
minimums and excessive delays terminate the attempt. Billing/credit/spend/usage
limits and semantic output failures are not transient retries. These settings
are not a total wall-clock deadline or permanent production thresholds.

Existing configuration options record SDK/request/schema versions and retry
settings. Provider identity is `openai-provider` version `1`; model identity is
`gpt-5.6-terra` with `alias:gpt-5.6-terra` version semantics, not an asserted dated
snapshot. The official endpoint is fixed, and credentials are read only at model
execution. `store=false` conveys no data-retention or confidentiality guarantee.
This implements accepted ADRs without changing the governed contracts or adding
a runtime tool, provider, or deployment architecture. Human review and Andrew's
final merge/release authority remain separate requirements.
