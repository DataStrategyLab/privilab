# Gate 5 claims and limitations — v1.0.0

Scope: the fixture Reference Demo at the manifest's tested candidate. These are
engineering-supported wording boundaries for Andrew's approval, not approval to
present externally. All six trade/regulatory tasks remain DRAFT and ineligible
for prospect demonstration. Mutable external facts require human/current-source
verification; no web verification was performed for this package.

Evidence keys: **S** = scenarios.json (actual captured observations); **C** =
manifest.json verification; **A** = accepted ADR-004 through ADR-010 and current
implementation; **U** = ../demo-ui-claims-checklist.md; **L** =
../../../architecture/live-eval.md and separately labeled historical PR #28.
References establish only the bounded behavior actually exercised.

| Claim | Allowed now | Evidence | Qualification | Prohibited/avoid |
| --- | --- | --- | --- | --- |
| PriviLAB reference implementation | Qualified | A, C, S | Local implementation of the approved P0 control sequence | Production implementation or general legal-research validation |
| Reference architecture | Qualified | README, accepted ADRs | Architectural pattern illustrated by this implementation | Approval of an organization's architecture |
| Controlled | Qualified | S, A | Explicit deterministic controls in synthetic scenarios | All risks controlled |
| Permission-aware | Qualified | S permission block, ADR-005 | Synthetic application permissions; BLOCK/UNKNOWN/unresolved CONDITIONAL fail closed | Legal entitlement, client consent, privilege determination |
| Authorization-scoped | Qualified | S, security tests in C, ADR-004 | SQLite retrieval filtering before source text enters model context | Production DMS enforcement or universal isolation proof |
| Source-grounded | Qualified | S positive and adversarial cases | Structural source/chunk and citation checks in this synthetic pack | Substantive truth, current law, or complete authority |
| Evaluated | Qualified | C, S | Named deterministic criteria and six golden cases | Broad benchmark, holdout validation, or legal adequacy |
| Traceable | Qualified | S history/reopen, ADR-007 | Minimum metadata reconstructs identity and disposition without replay | Full content replay, complete forensic audit, or certification |
| Human-reviewed | Only when specifically evidenced | S synthetic decisions; pending human-gate fields | UI supports separate local decisions; collector decisions are automated simulations | Representing automated clicks as lawyer/human approval |
| Provider-portable | Architecture qualification only | Provider contract, fixture/OpenAI paths, L | Abstraction exists; this rehearsal uses fixtures | Validated interchangeable behavior across untested vendors/models |
| Private | Not established | A, limitations below | Local fixture execution describes deployment, not a privacy finding | Blanket private/confidential deployment claim |
| ZDR / zero retention | Not established | L | Historical request setting store=false is not retention assurance | ZDR or provider-retention guarantee; CURRENT-SOURCE VERIFICATION REQUIRED |
| Air-gapped | Not established | Local offline verification | Offline fixture execution is a narrow observed fact | Certified air gap or live-provider air gap |
| Production-ready | No | A, limitations | Local reference deployment only | Production fitness or approval |
| Secure | No unqualified claim | C/security regressions | Describe specific tested boundaries | Guaranteed security or completed risk assessment |
| Security-certified | No | No certification evidence | None | Certification or audit endorsement |
| Privilege-preserving | No | No legal determination | Permissions are synthetic engineering controls | Privilege assurance |
| Privilege-compliant | No | No legal determination | Requires qualified analysis of actual context | Privilege compliance |
| OCG-compliant | No | No actual OCG analysis | No identifiable engagement terms are used | Compliance with firm/client OCGs |
| Compliant | No | No compliance determination | Discuss controls without a compliance conclusion | Blanket regulatory/ethical/legal compliance |
| Guaranteed confidentiality | No | No such evidence | No live client/matter content in this package | Confidentiality guarantee |
| Zero hallucinations | No | S negative cases | Detection is bounded by implemented checks | Guaranteed correctness or no unsupported output |
| Lower-cost / savings | No | L historical conditional cost telemetry | No comparison or billing validation; CURRENT-SOURCE VERIFICATION REQUIRED for pricing | Savings, invoice accuracy, future cost guarantee |
| Benchmark superiority | No | Six small synthetic cases | Control exercises only | Competitive ranking or general model quality inference |
| Law-firm approved | No | No approval evidence | None | Firm approval or adoption |
| Client approved | No | No approval evidence | None | Client approval or endorsement |
| OpenAI partnership/endorsement | No | Adapter implementation alone | CURRENT-SOURCE VERIFICATION REQUIRED before any separate relationship claim | Treating API use as partnership |
| Fireworks partnership/endorsement | No | No relationship evidence | CURRENT-SOURCE VERIFICATION REQUIRED | Partnership, integration, endorsement |
| Harvey partnership/endorsement | No | No relationship evidence | CURRENT-SOURCE VERIFICATION REQUIRED | Partnership, integration, endorsement |
| iManage partnership/endorsement | No | No relationship evidence | CURRENT-SOURCE VERIFICATION REQUIRED | DMS integration, partnership, endorsement |
| NetDocuments partnership/endorsement | No | No relationship evidence | CURRENT-SOURCE VERIFICATION REQUIRED | DMS integration, partnership, endorsement |

## Shared limitations

- Localhost/reference deployment, synthetic identities/context/permissions, and
  deterministic fixture outputs. The primary demo executes no live model.
- No production DMS, SSO, multi-tenancy, migration, or operations model.
- No production-readiness, legal/ethics, privilege, compliance, security
  certification, or confidentiality determination.
- No broad model benchmark or formal accessibility certification. Programmatic
  semantic checks do not replace keyboard, zoom, responsive, or human visual review.
- All six DSL-117 tasks: DRAFT; substantive reviewer/timestamp null;
  prospect_demo_eligible false. Automated PASS and synthetic APPROVE change none
  of those facts. Qualified review must complete all four release-critical
  trade-regulatory-substantive-review@1.0.0 criteria through the existing contract.
- Protected holdout is a placeholder: no holdout validation performed.
  Disposition is PENDING_DECISION, requiring a separately approved implementation
  issue or Andrew's explicit permitted Gate 5 condition/deferral.
- Metadata-only persistence cannot reconstruct an answer or replay an execution.
  Source IDs and configuration hashes establish identity, not substantive truth.
- The local container is supplemental; its contents do not reproduce the complete
  six-task source-checkout pack. Docker access may be environment-blocked.
- Historical live-smoke evidence is separate from this fixture candidate. Provider
  settings, current availability, pricing, retention, and external relationships
  have not been freshly verified. No live execution is needed for this rehearsal.
- Human approval, presentation acceptance, backup acceptance, Drive promotion, and
  Andrew's Gate 5 verdict remain pending unless the manifest links actual evidence.
