# Roadmap

**PriviLAB v0.1.0 — Developer Preview** describes local synthetic reference
workflows with source-only distribution. This roadmap describes direction, not a
release commitment or approval for client/production use.
[GitHub Releases](https://github.com/DataStrategyLab/privilab/releases) records
publication status, actual release dates, tags and downloadable source archives.
[Release status](docs/release-status.md) preserves the dated readiness assessment
and separate security/qualification holds.

## Implemented foundation

- Typed context and distinct fail-closed permission states.
- Authorization-scoped SQLite/FTS5 retrieval before model context.
- FixtureModelProvider and a provider contract with an OpenAI adapter.
- RunService orchestration, deterministic critical evaluation and separate
  synthetic Approve/Reject/Request revision actions.
- Metadata-only provenance/history, immutable decisions and restart persistence
  in the source-checkout preview.
- Six synthetic trade/regulatory golden cases and adversarial/control tests.
- Local live-smoke implementation with typed telemetry and offline mocks; default
  live SDK execution and hosted live-eval remain blocked pending qualification.
- Reproducible offline CI and a local FastAPI/Jinja preview.

## Current qualification work

Current advisory/OSS/source verification, qualified domain dispositions, claims,
human rehearsal/media acceptance and final prospect-release evidence remain
incomplete. Python/OS maintenance candidates require reviewed selection and
separate implementation/requalification; no successor is assumed accepted.
Public repository publication remains a distinct owner decision.

The held A1/A2 successor base candidates remain HOLD BOTH, with all 44 assessment
groups preliminarily unresolved and zero final case-level dispositions. Gate 2
is closed. Their qualification and any prospect rehearsal are separate from the
source-publication gate; a material issue in the actual published execution path
still requires disposition before publication.

## Planned model research — not shipped in v0.1.0

These are research directions, not approved integrations, delivery commitments or
permission to execute models. The v0.1.0 setup, live-SDK and deployment holds
remain in force. Research must preserve application-owned permission filtering
before model context, deterministic critical evaluation, separate human review
and metadata-oriented provenance.

| Research area | Proposed evaluation scope |
| --- | --- |
| NVIDIA Nemotron-family models | Evaluate applicable openly available models after checking each model's actual license, availability, inference/deployment requirements and workflow suitability. Consider bounded legal-workflow evaluations and provider-adapter experiments under approved scope. |
| Other open-weight models | Evaluate eligible models with common task-specific criteria: quality, groundedness, safety failures, latency, cost and deployment constraints. Explore fine-tuning only where permitted-use and evaluation evidence justify it. |
| Fireworks AI | Explore hosted open-weight inference and potential training workflows while preserving provider portability and PriviLAB's application-level permission, evaluation, review and provenance boundaries. |

Openly available weights do not establish a uniform license or unrestricted use.
Any experiment needs eligible public/synthetic or properly licensed data, defined
task criteria and an approved execution environment. Adoption must be supported
by model-specific rights and evaluation evidence. Additional providers, hosted
runtime or other architecture changes require an approved ADR and Andrew's
approval before implementation; this roadmap grants no such approval.

## Other candidate future work

Evidence may justify larger public/licensed evaluation sets, deeper workflow
evaluation and better deployment patterns. DMS/enterprise identity integration,
additional regulated-industry examples and hosted/private deployment patterns
require approved scope and architectural decisions before implementation.

No NVIDIA, Fireworks, Harvey/LAB, iManage, NetDocuments or other vendor partnership,
endorsement, compatibility, certified deployment or implemented integration is
asserted. Named external ecosystems are research context, not shipped capabilities.

## Contribute

Useful bounded proposals include documentation accuracy, meaningful regression
coverage, permission/retrieval contracts, safe public/synthetic examples and
provenance/evaluation clarity. Start through [CONTRIBUTING.md](CONTRIBUTING.md).
A proposal does not authorize an autonomous-agent framework, new runtime tools,
provider/database class or hosted deployment.
