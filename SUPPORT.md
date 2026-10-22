# Getting help

PriviLAB is a Developer Preview for local exploration with public or synthetic
data. Start with [Getting started](docs/getting-started.md),
[Reproducibility](docs/reproducibility.md), and
[Capabilities and limitations](docs/capabilities.md).

## Choose the right channel

| Need | Where to go |
| --- | --- |
| Installation, configuration, or usage question | Search [existing issues](https://github.com/DataStrategyLab/privilab/issues), then open a non-sensitive question if needed. |
| Reproducible bug | Open a bug report using the [issue chooser](https://github.com/DataStrategyLab/privilab/issues/new/choose). |
| Documentation correction or feature proposal | Use the proposal form in the [issue chooser](https://github.com/DataStrategyLab/privilab/issues/new/choose); follow [Contributing](CONTRIBUTING.md). |
| Suspected vulnerability or exposed credential | Follow [SECURITY.md](SECURITY.md) and report privately. |
| Harassment or other conduct concern | Follow the private reporting process in the [Code of Conduct](CODE_OF_CONDUCT.md). |
| Review responsibilities or project decisions | Read [Governance](GOVERNANCE.md) and the [review controls](docs/review/code_review.md). |

Public contributors do not need access to private project-management tools.
Repository access is required to use GitHub issues before public publication.

## Make a question or report useful

Include the source commit or release version, operating system and architecture,
the command or scenario involved, expected behavior, and the observed result.
Use a minimal example with public or synthetic inputs. Describe what you have
already tried and link related issues when useful.

Sanitize any error excerpts before posting. Do not attach environment dumps,
databases, credentials, client or matter content, personal information, or private
security reports. Avoid full logs when a short safe excerpt explains the problem.
See the [data-handling policy](DATA_HANDLING.md).

## Support boundaries

- Docker setup is unsupported; the retained Dockerfile is an unqualified
  engineering reference. Native uv/Python setup qualification is also pending.
  Check [local setup qualification](docs/release-status.md#local-setup-qualification)
  before a new networked bootstrap.
- Platform and setup requirements are documented in
  [Getting started](docs/getting-started.md); do not assume support for other
  platforms or deployment models.
- No guaranteed response time, maintenance period, backport commitment, or
  production-support SLA is offered for this Developer Preview.
- A filed issue, accepted proposal, or roadmap entry is not a delivery commitment.
  Maintainers assess scope, evidence, safety, and compatibility before accepting
  changes.
- Public source availability does not establish approval for production, hosted
  services, prospect demonstrations, or processing confidential client data.
  See the current [release status](docs/release-status.md).

The project does not provide legal advice or compliance determinations. Review
the documented limitations before choosing how to use or adapt the source.
