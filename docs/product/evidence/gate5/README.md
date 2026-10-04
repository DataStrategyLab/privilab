# DSL-120 Gate 5 release-evidence package — v1.0.0

This package supports Andrew's decision; it does not make that decision.
Engineering results are recorded in manifest.json and scenarios.json after actual
execution. Gate 5 verdict and decision timestamp remain null/PENDING.

## Identity and reproduction

Product candidate: `8d4bad1833431452bd6e99d2c238f5aa51cebbf5` (DSL-119 merged).
`evidence_tooling_head_sha` identifies the committed collector used for capture and
completed verification. `evidence_commit_sha` remains null until an external
Git/PR/Linear record binds the final package. Product/runtime/task/fixture/eval,
dependency/security/claims-bearing UI changes invalidate the old candidate;
evidence-only recording does not. The collector refuses a dirty checkout or a
material difference from this product candidate.

Use the existing DSL-120 source checkout and pinned environment. Do not reset or
repair an old DB. Choose never-used file paths for each capture:

```sh
./scripts/bootstrap.sh --ci
make ci
git diff --check
.venv/bin/python scripts/collect_gate5_evidence.py \
  --database "$PWD/.local/gate5/capture-01.sqlite3" \
  --output "$PWD/.local/gate5/capture-01.json"
mkdir -p .local/gate5
PRIVILAB_PREVIEW_DB="$PWD/.local/gate5/preview-01.sqlite3" make preview
```

Both collector paths are required, confined to ignored `.local/gate5/`, and must
be fresh. The collector reserves files exclusively; incomplete captures are
preserved, never deleted or overwritten. Rename the *new requested paths*, not
previous evidence, for another attempt. The preview DB must likewise be fresh;
`make preview` itself can reopen an existing DB, so the operator must check first.
Visit `http://127.0.0.1:8000`; stop only the preview process you started.

Capture uses existing ASGI routes and governed storage/evaluation/review APIs.
It is programmatic rehearsal, not a human visual/verbally delivered rehearsal.
Observed fields come from actual stored state; existing golden expectations are
comparison data only. The same stored evidence serializes canonically with sorted
keys, fixed ordering, stable enums, UTF-8, and a trailing newline. Fresh runs have
new IDs and timestamps. Local DBs, HTML, caches, raw logs, and media stay untracked.
Copy only inspected sanitized summaries into this package.

### Machine-readable contract

Manifest and scenario schemas are version `1`; package identity is
`dsl-120-gate5@1.0.0`. The manifest binds environment, commands, identities, hashes,
reference versions, limitations, review, backup, and pending decisions. Its hash
list excludes itself. Unknown human/external facts use null and explicit statuses.
Scenario evidence contains twelve named checks and ten distinct executions. Each
execution includes run/configuration/provider/task identities, time, permission,
stage flags, criteria/gate, and review metadata. No request/source/answer bodies
are retained. Golden fields never populate observations.

The three collector decisions preserve `synthetic-local-reviewer` and actual
stored timestamps, classified AUTOMATED_SYNTHETIC_DEMO_DECISION. They are separate
from every human-gated approval. Reviews have no separate ID in the existing
contract: cite run ID plus decision/timestamp, never invent a review ID.

History/reopen records read-only before/after row-count and canonical row-hash
snapshots across nine persistence tables, including runs, configurations,
permission conditions, source/chunk metadata, model executions/telemetry,
evaluations, and reviews. Execution guards must remain uncalled and HTTP reads
must succeed without draft/citation work areas. Snapshot equality is necessary
in addition to HTML checks.

## Trace → eval → repair evidence

Qualifying correction: DSL-116 pricing-source validation. No exploit payload or
sensitive raw finding is copied into this package.

| Step | Evidence / bounded conclusion |
| --- | --- |
| Material finding | PR #28 review thread `09f83740-a0b2-489a-937e-b11443ef3c17`, external thread `PRRT_kwDOT258Bc6nmBur`, created 2026-09-30T15:20:13Z. A P2 provenance-input validation defect was identified on `d13a07ce0ac857be9f8415640fad177bae5c0b2f`. |
| Reproduction / regression asset | Repair commit adds deterministic URL-boundary cases in tests/unit/test_telemetry.py and tests/integration/test_live_openai.py. Existing parent code and targeted repair diff establish the correction; historical PR records report 55 added cases and 202 targeted tests passing. |
| Targeted repair | `7ef3f182e19c9fa13f2583ee9e0270ce3f276fb4`: restrict accepted pricing-source origins and preserve bounded invalid-input handling without changing provider or release authority. |
| Broader regression | Andrew's thread reply `7f9b62ed-4faa-42e6-a44a-0c0683182323`, 2026-09-30T17:31:26Z, records full make ci: 42 contract, 2,156 unit/integration/security, smoke/golden, and diff check passing. This is a historical attestation; current verification is separately recorded in the manifest. |
| Independent review | Codex comment `7963702a-97c5-47fd-8f0b-f984b344c420`, 2026-09-30T17:42:03Z, identifies repaired head `7ef3f182e1` and reports no major issues. Review summary `11c34ecd-fd50-4d01-af59-41deb43255b9` records completed review at 17:42:04.722670Z. Actual hosted model ID is unavailable; do not infer it from current local config. |
| Human/merge record | Connected PR metadata records non-author approval at 2026-09-30T17:45:59Z and merged status. Local merge commit is `59ebcf82ca629f969165c38263315da599f9e5a6`, included in the tested candidate. This historical approval is not DSL-120 approval. |

Sources: [PR #28](https://github.com/DataStrategyLab/privilab/pull/28) and its
[original thread](https://github.com/DataStrategyLab/privilab/pull/28#discussion_r4146274458),
read through the approved Linear integration on 2026-10-04. Bounded summaries and
IDs are retained here rather than relying only on transient hosted logs. No
historical Actions run ID or retention period is invented. DSL-118's own record
says it closed an assertion gap without discovering a material product defect;
it is not substituted for this correction chain.

### Separately labeled historical live evidence

PR #28 records a governed GENERATED OpenAI smoke, provider openai-provider v1,
model gpt-5.6-terra; usage 206 input / 68 output / 274 total tokens; retry-inclusive
latency 3,804,079,208 ns; cost NOT_CALCULATED / PRICING_EVIDENCE_MISSING; one stored
evaluation and zero review decisions. Run ID is unavailable in the accessible PR
summary. This is historical supporting evidence, not current fixture execution,
fresh vendor verification, billing validation, or savings evidence.

## Backup assets and exact human rehearsal checklist

Canonical Drive folder URL: PENDING_DESIGNATION. Proposed organizational location,
not a claim that a folder exists: DSL Drive / PriviLAB / Gate 5 /
8d4bad183343 / dsl-120-gate5-v1.0.0. Andrew must designate the approved durable
folder before promotion. GitHub remains canonical for code-coupled evidence;
Linear remains the execution/status record.

Approved existing presentation asset: the unmodified DSL logo described in
[DSL-119's checklist](../demo-ui-claims-checklist.md), SHA-256
`351a2769ed240d03f178294b74b67df5a3bc95568bc26e722aba9e8d40034007`.
Its demo approval does not approve new screenshots, recordings, or wider use.

Human operator checklist (initial status: HUMAN ACTION REQUIRED):

1. Confirm manifest candidate/tooling identity, clean environment, and current
   script eligibility. Keep synthetic/reference and DRAFT disclosures visible.
2. At laptop size, narrow width, and actual 200% browser zoom, inspect layout,
   keyboard-only sequence, visible focus, skip link, disclosures, horizontal table
   scrolling, text status meaning, and control target sizes. Record date, reviewer,
   actual viewport/zoom, outcomes, and remediation; no accessibility certification.
3. Deliver the full 10–15 minute script and the three-minute script. Record actual
   durations, selected tasks/run IDs, interruptions, unsupported/implied claims,
   and reviewer acceptance. Timing targets are not measured results.
4. Capture six proposed backup screens: landing/banner; grounded draft/evaluation;
   permission stop with stages; generated BLOCK/disabled approval; final synthetic
   decision; metadata-only reopened history. Use only synthetic data, no browser
   account chrome, credentials, unrelated tabs, or unapproved material.
5. Optionally record the compressed script with the same disclosures and safe
   failure steps. Recording status stays NOT_RUN until created. Do not add video
   to Git. Inspect screenshots/recording visually and obtain Andrew's acceptance.
6. Hash accepted media, upload to the designated durable Drive folder, and record
   canonical file URLs, SHA-256, candidate, capture time, approver, and acceptance
   time. Until then, no accepted backup media exists in this package.
7. Rehearse fallback: stop the live demonstration, state the failure accurately,
   open accepted screenshots/recording, identify their candidate/date, and retain
   the limitation that backup playback is not a fresh execution.

## Release checklist and human-only gates

| Gate | Required evidence / owner |
| --- | --- |
| Engineering verification | Manifest command outcomes and twelve captured scenario checks; no unresolved source/license/asset issue. |
| Independent Codex review | Exact reviewed head/context/model where available; no Critical/High finding; Medium/Low resolved or explicitly dispositioned. |
| Non-author / CODEOWNER review | Actual approval on the relevant head under current rules. Locally verified CODEOWNERS names both owners; hosted enforcement has not been independently queried. |
| Substantive review | Andrew designates a qualified reviewer. Each externally used task must satisfy proposition-support, scope-discipline, uncertainty-handling, and draft-clarity through the existing versioned rubric with actual reviewer/time. Preserve DRAFT/false until then. |
| Holdout | PENDING_DECISION: separately approved implementation, or Andrew's permitted explicit deferral stating no validation was performed. No fabricated holdout. |
| Claims and visual acceptance | Human reviews scripts, wording, implied claims, mutable current-source facts if used, actual delivery, and backup assets. |
| Durable promotion | Promote the approved decision/readiness record and accepted media to designated Drive; record URLs and hashes. |
| Final authority | Andrew records verdict, time, conditions/exclusions, tested candidate, tooling head, and externally bound evidence package. Merge and release are separate decisions. |

Allowed later verdicts are INTERNAL DEMO READY, PROSPECT DEMO READY WITH CONDITIONS,
or NOT DEMO READY. No verdict is selected here. Prospect presentation cannot use
unreviewed tasks. No tag, GitHub Release, public publication, hosted deployment,
or fresh live model invocation is authorized by this package.

Engineering can recommend In Review only after required local verification and
independent review are complete with no blocking findings. Done requires the
full issue acceptance and Andrew's decision. Missing hosted CI metadata must be
filled from the actual PR workflow after it runs: record head SHA, workflow/job
identity, run ID/URL, conclusion, timestamps, suite counts, and retention/expiry
when known. Do not modify CI to obtain a checkbox or copy raw logs into Git.

## Verification, review, and remediation record

Frozen tooling head: `ac6e36dbec543badccd01874943ebafd354da0e7`.
Required bootstrap, make ci, and git diff --check passed from a clean checkout;
verification did not change repository-visible state. Observed suite counts:
42 contract tests; 2,190 unit/integration/security tests, including 13 new
collector checks; five deterministic smoke cases; six golden cases. Fixture and
license validation, format/lint, mypy, build smoke, and secret scanning passed.
The sanitized collector passed all twelve checks across ten independent runs.

The required make preview initially encountered a sandbox loopback-bind denial.
A separately approved loopback-only invocation then served the real application;
Codex browser automation exercised all six tasks and one synthetic APPROVE.
A browser reopen preserved all nine table snapshots. These are separate browser
run IDs, not the collector IDs and not human visual acceptance. Seven draft JPEG
captures exist at the ignored paths/hashes in the manifest. They are unaccepted
backup candidates; no recording or Drive upload was performed. One browser
locator click failed before submission; scrolling to the visible control and a
coordinate click completed the action once, as confirmed by its stored decision.

`make container-build` exited 2 because the sandbox cannot access the Docker
socket. Container preview was NOT_RUN; no Docker boundary was changed.

Development remediation: a content-exclusion test initially treated the generic
query word “synthetic” inside a permitted metadata ID as leaked query text. The
assertion was corrected to check complete JSON string values, and checks exclude
actual task/fixture-answer bodies. No product defect or behavior change resulted.

Independent review results will be recorded after the prepared package commit.
All human gates remain PENDING.
