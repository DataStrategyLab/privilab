# Developer Preview release status

## Publication record

**PriviLAB v0.1.0 — Developer Preview** has an Apache-2.0 source-only distribution
scope using public/synthetic fixtures.
[GitHub Releases](https://github.com/DataStrategyLab/privilab/releases) is the
authoritative record of whether a version has been published, its actual date,
tag and downloadable source archives. This document is not a live publication
or approval ledger. Source publication does not resolve the security findings
or qualification holds below.

## Historical pre-publication readiness assessment

**Assessment date: October 23, 2026 (America/New_York), before publication.**
The following table records that assessment's requirements and outstanding
decisions at the time. Its pending entries do not describe later publication
status; consult GitHub Releases for the publication record. Merge, visibility,
tag and release actions require separate maintainer decisions after the required
checks; a target date is not authorization or a PASS.

| Area | Current disposition | Evidence/decision required |
| --- | --- | --- |
| Public files, history and repository surfaces | Review required | Exact release tree and reachable history; issues/PRs, Actions logs/artifacts and other exposed surfaces; owner clearance of exceptions |
| Source, fixture and contributor rights | Prior defined source scope approved; final delta check required | Preserve contributor credit, Apache-2.0 source terms and applicable third-party notices; no new rights inferred |
| Branding and attribution | Existing included logo scope approved | No new assets; Andrew credited as Creator & Lead Architect; trademark/endorsement rights remain reserved |
| Actual published source execution path | Applicable material issues require disposition | Current local tool/runtime/dependency path, safe defaults and bounded claims; source-only does not waive a relevant security concern |
| Final PR verification and review | Pending final head | Canonical `make ci` in an existing approved offline-capable environment, disclosure/link checks, dedicated Codex review and genuine non-author human/CODEOWNER approval; no held bootstrap execution |
| Repository controls and publication | Owner decision pending | Effective settings, approved publication route, final GO, source-only pre-release and actual public readback |
| Wheel, binary, container or hosted distribution | Excluded | Separate artifact rights, security qualification and distribution approval would be required |

The release contains source and GitHub's automatic source archives only. The
Dockerfile and local bootstrap instructions are source examples, not approval to
distribute an image, wheel, managed runtime or dependency bundle. The retained
historical application configuration, held successor bases and a future complete
successor application are distinct artifacts.

## Local setup qualification

- **Fresh native networked setup: HOLD.** Patched uv 0.13.4 and managed Python
  3.13.17 identities and bounded CI checks do not qualify every active TLS path.
  Host Python/OpenSSL, SDK native trust, bootstrap curl and any networked pip
  require their own evidence. Current public guides provide no bootstrap
  execution procedure. Retained bootstrap/CI sources remain engineering
  references; existing CI authorization does not clear general host setup.
- **Default live SDK: disabled.** Client construction fails before credentials
  or HTTP access; no runtime opt-in overrides the restriction. This restriction
  does not remediate T01, establish affected-chain rejection or provide native
  trust equivalence. An unmerged CA-trust prototype is outside this candidate.
- **Fixture exploration: existing approved environments only.** Source inspection
  and documentation contribution need no native execution. Fixture preview and
  canonical offline CI remain usable where locked tools/inputs were already
  provisioned and the environment separately approved; this is not a fresh
  public installation qualification or a four-platform support claim.
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
from fixture preview/CI but default client construction is now disabled. No live
or paid model call is required for normal preview or CI. See
[capabilities](capabilities.md) and [getting started](getting-started.md).

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

## Distribution scope

[v0.1.0 release notes](release-notes-v0.1.0.md) describe Apache-2.0 source and
automatic source archives only. The release format is a GitHub **pre-release**.
No wheel, dependency/runtime bundle, binary, container image or hosted service
is included. Consult [GitHub Releases](https://github.com/DataStrategyLab/privilab/releases)
for actual publication status, date and tag. Publication records do not qualify
native setup, live SDK use, Docker or any separately held deployment scope.

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
