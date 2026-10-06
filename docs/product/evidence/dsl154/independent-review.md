# Separate independent-review handoff

Status: **PENDING — NOT EXECUTED IN AUTHOR SESSION**.
Configured review model: `gpt-6-astra` from unchanged `.codex/config.toml`.
The actual reviewer/model/session/timestamps/findings remain null until execution.

## Exact target and setup

Use the concrete final committed DSL-154 HEAD **H** supplied in the author-session
handoff. H is the final evidence/tooling/package commit, not merely the earlier
collector-freeze commit T and not the product-candidate commit. The manifest binds
T for the captures; the handoff separately binds H for review. This avoids a
self-referential commit hash in tracked files.

In a separate reviewer context, create/use a clean checkout of exact H. Confirm
`git rev-parse HEAD` equals H and `git status --short` is empty. Compare against
base `f19f5542105661614c225691c3df780264de8262`. Inspect the complete candidate
behavior as required by the brief, not only changed lines. Do not modify `.codex`
configuration, enable networking, or invoke paid/live evaluation.

Prepared dedicated review command, run with that verified checkout as cwd:

```sh
codex review --base f19f5542105661614c225691c3df780264de8262
```

Provide the following brief to the independent reviewer context before launching
its dedicated review. The author session must not launch or count this review.

> Review final DSL-154 HEAD H against frozen product candidate/base
> f19f5542105661614c225691c3df780264de8262. Assess both unchanged candidate behavior
> supporting qualification and every DSL-154-added collector, test, manifest,
> evidence, claims, and handoff change. Check issue/ADR compliance, identity
> separation, fresh-checkout/cache-backed evidence, historical immutability,
> build/dependency/container posture, permissions/isolation, untrusted-content
> boundaries, evaluator integrity, provenance/minimum retention, repeatability,
> supply-chain/OSS scope, holdout/domain-review separation, claims/current-source
> gaps, and reconstructability. Verify observations and limitations. Passing
> tests and synthetic reviews do not establish legal/domain correctness or
> release approval. No Critical/High finding may be silently dispositioned.

## Evidence to inspect

Read this package's README, manifest, verification, acceptance matrix, scenarios,
repeatability, security evidence, supply chain/SBOM, substantive review worksheets,
current-source queue, claims, demo materials and handoffs. Review new collector/tests
and the full diff from the base. Confirm historical Gate 5 and every material
product/runtime/dependency/task/fixture/evaluator/permission path are unchanged.

Fresh author qualification and final-H CI are separate from independent verification.
Record exact reviewed H, base, actual configured/executed model where observable,
session, timestamps, checks, limitations, findings/severity and dispositions.
Critical/High blocks later progression. Medium/Low must be fixed or explicitly
dispositioned before release. Missing independent review prevents recommending
In Review. Non-author human approval and Andrew's final merge/release decision
follow independent review and remain separate gates.
