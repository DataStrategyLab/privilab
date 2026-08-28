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

## Out of scope for P0

Hosted deployment, production hardening claims, client/DMS integrations,
runtime MCP, autonomous agents, model-controlled tools, and live OpenAI execution
are not authorized by this bootstrap.
