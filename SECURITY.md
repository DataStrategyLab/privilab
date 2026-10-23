# Security policy

PriviLAB 0.1.x is an experimental Developer Preview for local public/synthetic
reference workflows. No production-support SLA, certification or safe handling
of actual client/matter data is established. Current source/runtime review status
is described in [release status](docs/release-status.md).

## Setup qualification

The native uv/Python bootstrap remains under security review; wait for maintainer
clearance before new networked setup. Docker setup is on a temporary
security-qualification hold; the Dockerfile remains an engineering reference.
While the hold applies, do not build, run or expose it for general
external, shared, prospect, client, hosted or production use. Executable container
targets, immutable image references and loopback mappings do not establish
security qualification. See
[local setup qualification](docs/release-status.md#local-setup-qualification).

## Report privately

Send suspected vulnerabilities to
[andrew@datastrategylab.com](mailto:andrew@datastrategylab.com), the approved
private project contact. Start with a minimal summary, affected version/source
SHA, impact and safe reproduction outline. Arrange an approved restricted transfer
before sending detailed exploit material or private inventories.

Do not file public issues/PRs containing credentials, client content, sensitive
security findings or exploit details. Do not upload raw findings to shared chats
or ordinary project-management records. Maintain privately retained evidence and
share only approved sanitized summaries. Do not assume a GitHub private-reporting
feature is enabled unless it is visibly available and maintainer-confirmed.

No guaranteed response or remediation time is advertised. Maintainers assess
reports, coordinate reproduction/remediation and agree disclosure timing with the
reporter where feasible. Publication approval and risk acceptance remain owner
responsibilities; a scanner count alone does not supply them.

## Existing boundaries

- Permission filtering occurs before source content enters model context.
- BLOCK, UNKNOWN and unresolved CONDITIONAL fail closed.
- Deterministic critical failures prevent approval; human review stays separate.
- Local preview binds to loopback by default and uses synthetic reviewer identity.
- Run history retains minimum metadata, not prompt/source/answer bodies or secrets.
- After bootstrap, `make ci` is offline/secret-free; Gitleaks checks history/worktree.
- CI has read-only repository permissions and no deployment/model/client secrets.
- Hosted live-eval remains deliberately blocked; local live smoke requires explicit
  opt-in and is outside CI.

These are bounded implementation controls, not a penetration-test conclusion or
absence-of-vulnerabilities claim. Do not expose this local preview as a public service.

## OpenAI adapter

### SDK trust prototype

The SDK-only CA configuration is an **unqualified prototype**. Its packaged
trust policy has `network_use_approved: false`, so the default live client fails
closed before creating an HTTP client. Offline fixture preview remains usable.
Do not enable the policy or treat passing offline tests as native TLS clearance.

The prototype authenticates the exact certifi 2026.10.19 bundle and supplies its
bytes to a standard-library SSL context through the supported SDK HTTP client.
It does not union host roots, accept ambient CA/proxy settings, follow redirects
or disable certificate/hostname verification. A pinned policy enforces a proposed
30-day review window; that window is a maintenance cutoff, not a guarantee that
the bundle remains safe. New applicable advisories require immediate reassessment.

Static CA trust can lose native macOS revocation, distrust and intermediate-chain
handling. Equivalent incident-specific protection has **not** been established.
No authentic affected-chain negative or independent positive control is credited.
The [trust comparison and rollback](docs/architecture/sdk-tls-trust.md) records the
acceptance limitations. Owner policy/architecture acceptance and independent
review remain required. Python defaults, uv alternate stores, bootstrap curl,
networked pip, other platforms and all existing release holds are separate.

The adapter uses the official SDK behind the application provider contract, with
credentials read only at execution from `OPENAI_API_KEY`. It uses a fixed official
endpoint, bounded retries/timeouts and sanitized failures. Responses requests
disable storage, streaming, background execution, tools and truncation.
`store=false` is request configuration, not a ZDR, confidentiality, privilege or
compliance guarantee. Typed live usage/latency/cost metadata is described in the
[local live guide](docs/architecture/live-eval.md); raw payloads/credentials are not
stored in application provenance.

## Exclusions

Production authentication, hosted deployment, client/DMS integrations, autonomous
model-controlled tools, runtime MCP, additional providers and automatic model
fallback are outside the current approved implementation. Use the private channel
for unresolved material concerns; do not try to clear them by changing marketing
wording or adding a roadmap notice.
