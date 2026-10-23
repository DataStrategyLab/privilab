# Developer Preview release status

**Status snapshot: October 22, 2026 (America/New_York).**
**Planned source-only release target: Wednesday, October 21, 2026.**
**Publication status: not published yet; final owner decision pending.**

The proposed release is **PriviLAB v0.1.0 Developer Preview**, a public,
Apache-2.0 source-only reference implementation using public/synthetic fixtures.
The target date does not authorize merge, public repository visibility, a tag or
release publication. Andrew separately makes those decisions after the final
release-readiness review. If a required check fails, report the actual blocker;
do not backdate a release or treat the target as a PASS.

## Source-publication gate

| Area | Current disposition | Evidence/decision required |
| --- | --- | --- |
| Public files, history and repository surfaces | Review required | Exact release tree and reachable history; issues/PRs, Actions logs/artifacts and other exposed surfaces; owner clearance of exceptions |
| Source, fixture and contributor rights | Owner confirmation required | Affirmative Apache-2.0 publishing authority and applicable notices for the actual included bytes |
| Branding and attribution | Owner confirmation required | Public display/redistribution scope for included DSL marks; Andrew credited as Creator & Lead Architect; trademark rights remain separate |
| Actual published source execution path | Applicable material issues require disposition | Current local tool/runtime/dependency path, safe defaults and bounded claims; source-only does not waive a relevant security concern |
| Final PR verification and review | Pending final head | Pinned bootstrap, `make ci`, disclosure/link checks, dedicated Codex review and genuine non-author human/CODEOWNER approval |
| Repository controls and publication | Owner decision pending | Effective settings, approved publication route, final GO, source-only pre-release and actual public readback |
| Wheel, binary, container or hosted distribution | Excluded | Separate artifact rights, security qualification and distribution approval would be required |

The release contains source and GitHub's automatic source archives only. The
Dockerfile and local bootstrap instructions are source examples, not approval to
distribute an image, wheel, managed runtime or dependency bundle. The retained
historical application configuration, held successor bases and a future complete
successor application are distinct artifacts.

## Local setup qualification

- **Native setup: qualification pending.** The patched uv 0.13.4 / Python 3.13.17 bootstrap candidate remains
  under artifact and CI qualification review. Wait for maintainer clearance before a new networked
  bootstrap; the documented commands describe the existing engineering path.
  The intended public preview is native localhost with public/synthetic inputs
  only after the applicable tool/runtime findings have been resolved or explicitly
  dispositioned. This documentation does not apply a tool or interpreter fix.
- **Docker: temporary security-qualification hold.**
  [ADR-008](decisions/ADR-008-preview-deployment.md) permits a local container as an
  architectural option. This release-specific hold preserves that decision;
  architectural permission does not establish security qualification for the
  current container. The Dockerfile remains for engineering traceability and
  reproducibility review. While the hold applies, do not build, run or expose it
  for general external, shared, prospect, client,
  hosted or production use. Existing executable Makefile targets are retained;
  their presence does not authorize execution. Docker operation needs separate
  security qualification and maintainer approval. No base-image update or
  security clearance is established by this documentation change.

Historical deployment decisions and captured evidence retain their original
scope. They do not establish current release-specific runtime qualification.

## Available for local engineering exploration

Synthetic fixture execution, permission-scoped retrieval, deterministic critical
evaluation, separate synthetic review, metadata history and offline verification
are implemented. An OpenAI adapter and opt-in local live smoke exist separately
from fixture preview/CI. No live or paid model call is required for normal preview
or CI. See [capabilities](capabilities.md) and [getting started](getting-started.md).

## Separate qualification work remains open

| Area | Current disposition | Separate evidence/decision required |
| --- | --- | --- |
| Held A1/A2 successor base candidates | HOLD BOTH; 44 groups preliminarily unresolved; zero final case-level dispositions | Remaining build/runtime/patch/mitigation evidence and scoped human confirmation; no selection or implementation authorized |
| Security implementation gate | Gate 2 CLOSED; B04 OPEN | Attributable assessment and owner decisions for the applicable artifact |
| Qualified domain/task review | Pending | Qualified substantive review, source/proposition/currentness and task eligibility |
| Prospect rehearsal and claims/media acceptance | Pending prerequisites | Actual human rehearsal, accepted disclosures and same-candidate backup media |
| Durable prospect release record | Pending | Accepted evidence and final owner decision |

Final successor-base case dispositions and prospect rehearsal are not prerequisites
for source visibility by themselves. Source publication does not close them or
approve substantive/prospect use. Any material issue applicable to the actual
source and documented local execution path must still be addressed for that
publication scope.

## Existing limitations remain in force

- All six domain tasks remain INTERNAL_ONLY for substantive/prospect use pending
  qualified eligibility and prospect-release decisions. Source visibility alone
  does not approve them.
- No protected holdout validation was performed. Evidence is disclosed synthetic/
  golden control behavior and deterministic fixture repeatability.
- Automated structural PASS is distinct from domain correctness and human approval.
- There is no production identity/DMS integration, hosted runtime, model-controlled
  tool execution or runtime MCP.
- Metadata supports reconstruction of identity/disposition, not answer replay.
- Model availability, privacy/ZDR, pricing/savings, certification, production
  fitness and vendor endorsement are not established by the repository.

Raw vulnerability findings, private reports, client content and secrets are not
public release material. Keep the release-readiness report sanitized and preserve
private evidence in its approved restricted custody.
