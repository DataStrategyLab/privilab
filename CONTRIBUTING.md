# Contributing to PriviLAB

Thank you for helping improve controlled, permission-aware AI workflows.
Read the [Code of Conduct](CODE_OF_CONDUCT.md), [data policy](DATA_HANDLING.md)
and [security policy](SECURITY.md) before submitting content.
See [Support](SUPPORT.md) for usage questions and reporting channels, and
[Governance](GOVERNANCE.md) for responsibilities and project decisions.
[Contributors and acknowledgments](CONTRIBUTORS.md) records engineering and
historical technical-review credit.

## Start with an issue

Use [GitHub issues](https://github.com/DataStrategyLab/privilab/issues) for a
non-sensitive bug, documentation correction or bounded feature proposal. Include
expected/actual behavior, version or source SHA, platform, reproduction steps and
sanitized synthetic examples. Check existing issues/PRs first.

Public contributors do not need access to private Linear. Maintainers map accepted
work into one Ready engineering issue with scope, acceptance criteria, tests and
preview needs. Read [AGENTS.md](AGENTS.md) and relevant
[ADRs](docs/decisions/README.md). Work from an isolated branch/worktree and keep
changes inside the accepted scope. For routine documentation fixes, a maintainer
can define that scope from the GitHub report.

New runtime/provider/framework/database/hosted deployment/DMS or model-controlled
tool architecture needs an approved ADR and Andrew's approval. A roadmap entry
is not authorization to introduce it.

## Set up and verify

Fork/clone the repository and create a branch from current main. Maintainers use
`codex/` for Codex-authored branches. Follow [Getting started](docs/getting-started.md).

```sh
./scripts/bootstrap.sh --ci
make ci
git diff --check
```

`make ci` is the canonical verification; do not replace it with selected tests.
No API key or paid/live call is needed. Run the issue's required local preview
and record actual observations when user-facing behavior or preview instructions
change. Use synthetic data and a fresh ignored DB when appropriate. See
[Reproducibility](docs/reproducibility.md).

## Code, tests and data

- Use the existing Python/FastAPI/Jinja/SQLite boundaries and typed contracts.
- Add meaningful regression coverage for behavior changes; documentation-only
  fixes need accurate commands, working links and appropriate existing checks.
- Preserve authorization before source content enters model context. Permission
  BLOCK, UNKNOWN and unresolved CONDITIONAL fail closed.
- Keep human/domain review separate from automated structural evaluation.
- Register third-party/fixture origin, license, permitted use and hashes in
  `licenses/registry.yaml` and the applicable manifest. Never invent permission.
- Keep `.venv`, `.tools`, `.local`, caches, DBs, outputs and local environment files
  untracked. Do not edit `uv.lock` manually; use the pinned uv workflow.
- Never submit client/matter/privileged content, identifiable OCG/engagement terms,
  restricted legal databases, secrets or private vulnerability findings.

## Pull requests and review

Link the public GitHub issue and, when available, the maintainer's engineering
issue. Explain the problem, final behavior, scope, verification, preview results
and known limits. Keep screenshots/logs free of sensitive/private content.
AI-assisted contributions must be understood by their author and meet the same
requirements as other changes.

The maintainer workflow requires:

1. Issue-scoped implementation and `make ci`, plus required preview evidence.
2. Dedicated Codex `/review` using the configured independent review model.
3. Resolution of all Critical/High findings; lower findings dispositioned as required.
4. One non-author human approval and applicable CODEOWNER approvals.
5. Andrew's separate final merge and release decision.

Contributors need not install Codex to file an issue or open a proposal; maintainers
coordinate the dedicated review by commenting `@codex review` on the PR. The
[pull request review guide](.github/CODE_REVIEW.md) describes the shared review
standards and how to handle sensitive findings. A merged PR does not automatically
make the engineering issue Done or authorize a prospect/production release. See
[review controls](docs/review/code_review.md).

## Contribution rights

Submit only work you are entitled to contribute. Unless explicitly stated otherwise,
intentional contributions to project-authored Apache-2.0 work are submitted under
the same license, as described in LICENSE section 5. Identify any different terms
and required notices before submission; maintainers must approve compatibility.
No new CLA or sign-off requirement is introduced by this document. Third-party
materials and project branding retain their own applicable boundaries; see the
[license guide](licenses/README.md).

## Private concerns

Send vulnerabilities through [SECURITY.md](SECURITY.md). Conduct concerns go
privately to [conduct@datastrategylab.com](mailto:conduct@datastrategylab.com),
following the [Code of Conduct](CODE_OF_CONDUCT.md#private-conduct-reporting).
Do not place sensitive reports in public issues, PRs or shared project chats.
