# DSL-154 claims and limitations — 1.0.0

Applies only to the manifest's exact candidate/configuration. "Qualified" below
means bounded engineering support, not permission to present externally. Human
claims approval is **PENDING for every row**. Prospect task eligibility, qualified
review and Andrew's Gate 5 decision remain separate. References are current-package
files unless labeled historical. Mutable facts are queued in current-source-queue.json;
repository text alone has not freshly verified any external fact.

| Claim | Allowed now? | Supporting evidence | Required qualification | Mutable dependency | Prohibited overstatement |
| --- | --- | --- | --- | --- | --- |
| Reference implementation | Qualified | manifest; scenarios; accepted ADRs | Local synthetic approved P0 workflow | None for local observation | Production implementation or legal-research validation |
| Controlled | Qualified | scenarios; security-evidence | Name specific exercised controls | None for local observation | All risks controlled |
| Permission-aware | Qualified | permission scenarios; security tests | Synthetic deterministic policy; distinct states | None for local observation | Legal entitlement, client consent or privilege determination |
| Authorization-scoped | Qualified | cross-context tests; source IDs | SQLite filtering before model input | None for local observation | DMS/SSO enforcement or universal isolation proof |
| Source-grounded | Qualified | source worksheets; positive/negative cases | Structural synthetic source/chunk checks | Current law if separately asserted | Substantive truth or complete legal authority |
| Evaluated | Qualified | CI; six golden cases; four critical criteria | Versioned deterministic checks | Benchmark facts if separately asserted | Broad legal benchmark or holdout validation |
| Traceable | Qualified | run IDs/config hashes; history snapshots | Metadata reconstructs identity/disposition, not answer replay | None for local observation | Full forensic audit or retained-content replay |
| Human-reviewed | Only with actual evidence | synthetic decisions; pending worksheets | UI supports decisions; automated clicks are simulations | Named reviewer evidence | Lawyer/domain approval inferred from APPROVE |
| Provider-portable | Architecture qualification only | provider contract; offline adapter tests | Fixture path qualified; alternate outcomes not established | Model/API/provider availability | Validated cross-vendor interchangeability |
| Private | Not established | local execution boundary | Locality is deployment evidence only | Provider data controls/contracts | Guaranteed privacy or confidentiality |
| ZDR / zero retention | Not established | local request setting; external queue | store=false is only configuration | Provider data controls/contracts | Zero retention assurance |
| Air-gapped | Not established | offline fixture checks | State only observed offline execution | Deployment certification if claimed | Certified air gap or live-provider air gap |
| Production-ready | No | ADR-008; limitations | Local reference only | None supplies missing approval | Production fitness |
| Secure / security-certified | No unqualified claim | security regressions | Name covered boundaries and limits | Security/advisory/certification evidence | Security guarantee or certification |
| Privilege-preserving / compliant | No | no legal determination | Synthetic engineering permissions only | Qualified legal analysis | Privilege or work-product assurance |
| OCG / client / regulatory compliance | No | no actual OCG/client analysis | No identifiable terms used | Qualified contextual analysis | Compliance determination |
| Guaranteed confidentiality | No | no guarantee evidence | No live client/matter data | Provider/deployment contracts | Confidentiality guarantee |
| Zero hallucinations | No | intentional negative cases | Detection limited to checks exercised | None | Guaranteed correctness |
| Lower cost / savings | No | fixture telemetry N/A | No billing or comparative study | Pricing/comparison data | Savings, invoice accuracy, future cost guarantee |
| Benchmark superiority | No | small synthetic golden set | Control exercises only | Comparable primary benchmark evidence | Ranking or generalized model performance |
| Law-firm/client approved | No | no approval evidence | No customer endorsement inferred | Actual approval documentation | Approval/adoption claim |
| OpenAI partnership/endorsement | No | adapter exists; external queue | API use does not establish relationship | Written authorization | Partnership or endorsement |
| Fireworks partnership/integration | No | roadmap wording only | No implemented Fireworks path | Current docs/relationship evidence | Implemented compatibility or endorsement |
| Harvey/LAB partnership/compatibility | No | reference only | No imported framework/tasks/runtime | Project/license/relationship evidence | Endorsement or benchmark comparability |
| iManage/NetDocuments integration | No | future-pattern references only | No runtime DMS integration | Product/relationship evidence | Integration, partnership or endorsement |
| PriviLAB is open source | No | README licensing boundary | Private DSL reference code; public release not approved | Andrew's separate release/license decision | Public-license or reuse rights implied by dependencies |
| Uses open-source dependencies | Qualified | lock; registry; supply-chain; SBOM | Component-specific licenses/notices, separate from DSL code/data | Current license/advisory verification | Entire application is open source or IP-cleared |

Preferred bounded framing, subject to human claims approval:

> PriviLAB is DSL's reference implementation for controlled legal-AI workflows.
> This candidate demonstrates permission-aware retrieval, source-grounded outputs,
> task-specific evaluation, human review, safe-failure behavior, and traceable run
> evidence using approved public or synthetic materials.

Explain that "human review" describes an available workflow control; this package's
local decisions are synthetic exercises. The sentence is not a guarantee or release.

## Shared limitations

- All six tasks remain DRAFT/prospect-ineligible. Structural checks cannot approve
  substantive legal propositions. The synthetic notice supplies no legal authority.
- No protected holdout validation; Option B awaits Andrew. Golden cases are not a holdout.
- Fixed fixture outputs; no live model stability, fresh live execution, measured
  provider usage/cost, legal adequacy, benchmark equivalence, or vendor currentness.
- Fresh checkout/cache-backed installation is not independent upstream retrieval.
- SBOM is a lock export (uv labels export experimental), not a vulnerability scan,
  attestation, container OS SBOM, SLSA compliance, or certification.
- Localhost/source-checkout workflow; no hosted runtime, production DMS/SSO,
  multi-tenancy, autonomous model tools, runtime MCP, or new provider.
- Supplemental container lacks the complete six-task checkout tree; environment
  access and any resulting operator verification are recorded separately.
- Metadata/history cannot reproduce an answer. Hashes establish identity, not truth.
- Automated preview checks do not replace human keyboard/zoom/visual acceptance.
- Independent review, non-author approval, current facts, substantive review,
  rehearsal, accepted backup media, Drive promotion and final Gate 5 remain pending.
