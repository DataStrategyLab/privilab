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

The source-only preview disables default live SDK construction before credential
access or HTTP-client creation. Opt-in flags and credentials do not lift the hold.
This is a temporary execution restriction, not a correction to host Python,
OpenSSL, curl, pip or native certificate stores. No affected-chain rejection or
equivalent native trust protections have been established. The unmerged SDK trust
prototype is not part of this release candidate.

Current public guides omit actionable networked setup and live-run procedures.
Retained bootstrap and container sources, CI configuration and historical records
remain engineering references; their presence is not execution approval. Existing
CI evidence supports its tested environment only. Do not disable certificate or
hostname verification, change host trust stores, or add unsafe fallback paths.

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
- Hosted live-eval and default local live SDK construction are blocked; offline
  fixture preview/CI do not require model calls or credentials.

These are bounded implementation controls, not a penetration-test conclusion or
absence-of-vulnerabilities claim. Do not expose this local preview as a public service.

## OpenAI adapter

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
