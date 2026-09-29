# Security policy

PriviLAB P0 is a local reference demo, not a production service.

## Reporting

Do not file public issues containing credentials, sensitive security findings,
client information, or exploit details. Report such findings privately to the
repository owner, Andrew Tsintsiruk.

## Engineering controls

- `make ci` runs without API secrets or external network after bootstrap.
- Gitleaks scans repository history and the current worktree.
- Codex workspace networking and web search are disabled by project config.
- GitHub Actions use read-only repository permissions and no deploy/model/client
  credentials.
- Application preview binds to loopback by default.
- Critical and High review findings block merge.

## Approved OpenAI adapter boundary

DSL-114 satisfied ADR-003's fixture-first prerequisite. DSL-115 adds the official
OpenAI SDK behind the existing provider contract for exactly `gpt-5.6-terra`.
The governed `RunService.from_openai` factory preserves authorization before
model input. Credentials are read from `OPENAI_API_KEY` only at execution; the
official API endpoint is fixed. The adapter exposes sanitized failures and no
raw SDK exception chains, and persists no credentials, payloads, or usage.

Responses requests explicitly disable storage, streaming, background execution,
tools, and truncation. `store=false` is only request configuration: it is not a
ZDR, privacy, confidentiality, privilege, compliance, or security guarantee.
DSL-115 verification uses offline fakes. Live smoke execution and telemetry
integration belong to DSL-116; the live-eval workflow remains blocked.

## Out of scope for P0

Hosted deployment, production hardening claims, client/DMS integrations,
runtime MCP, autonomous agents, model-controlled tools, alternate model providers,
and automatic model fallback remain unauthorized.
