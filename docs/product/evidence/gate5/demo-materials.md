# Gate 5 demo materials — v1.0.0

Audience: Andrew and internal engineering/domain reviewers. These scripts are
prepared for human rehearsal; completion is not asserted. All task executions
are synthetic/internal DRAFT. No current DSL-117 task is prospect-eligible.
External delivery excludes unapproved tasks and requires Andrew's approved script.
Use the exact candidate and qualifications in [claims and limitations](claims-and-limitations.md).

## Primary script — 12 minutes, with up to 3 minutes of questions

| Time | Action | Bounded narration / observable check |
| --- | --- | --- |
| 0:00–1:00 | Open the localhost landing page; show the persistent banner and scenario guide. | “PriviLAB Reference Demo: a local, synthetic implementation of a permission-aware control sequence. Fixed fixture answers demonstrate controls; they do not measure a live model or legal correctness.” |
| 1:00–2:30 | Run `trade-regulatory.grounded-happy-path`. Expand context, permission, authorized sources, and draft. | Follow context → permission → authorized evidence → draft. Identify the synthetic scope and source/chunk metadata. Call the output a draft, presented for reviewer consideration. |
| 2:30–3:30 | Expand evaluation and show four criteria, automated PASS, and available decisions. | “This gate checks the defined structural criteria. PASS is not substantive approval or release permission.” On this separate eligible run select Approve; explicitly identify the synthetic-local-reviewer exercise. |
| 3:30–4:30 | Run `trade-regulatory.insufficient-source`. | Read the bounded insufficient-source qualification on screen. “The supplied source does not establish the proposition; that does not say no requirement exists.” Automated PASS does not establish adequate legal research. |
| 4:30–5:30 | Run `trade-regulatory.permission-block`. | Show permission BLOCK, stopped status, and retrieval/model not reached. No draft or human-review work area. A recorded stop evaluation must not be confused with model generation. |
| 5:30–6:00 | Start a new grounded-happy-path run. | Point out the distinct run ID and independent success. The stopped run remains unchanged. |
| 6:00–7:15 | Run `trade-regulatory.critical-eval-failure`, then `trade-regulatory.citation-grounding-challenge`. | Both generate fixture output and receive automated BLOCK. Explain missing evidence versus a non-resolving citation; show approval unavailable. Do not override the gate. |
| 7:15–8:15 | Run `trade-regulatory.malicious-source-injection`. | Source instructions remain untrusted data. Explain that the deliberate fixture citation to excluded evidence fails checks. No model-controlled tool or release authority exists. Avoid claiming general prompt-injection immunity. |
| 8:15–9:30 | Run grounded-happy-path twice more; Reject one and Request revision on the other. | Demonstrate distinct immutable decisions on distinct run IDs. These local synthetic actions do not qualify tasks for prospect use or approve release. |
| 9:30–10:30 | Open history and reopen earlier positive, blocked, and decided runs. | Identity, configuration, gate, and review metadata remain. Draft/citation bodies are absent. Point to collector persistence hashes/call guards as programmatic no-replay evidence. |
| 10:30–12:00 | Show the evidence manifest, limitations, and pending decisions. | Distinguish tested candidate, tooling execution commit, final package, and Andrew's decision. Disclose DRAFT tasks, no holdout, fixture primary path, and pending human gates. |

Keep a run-ID note for each live presentation action; do not substitute these IDs
for the separate collector capture. If a step fails, record it, switch to accepted
backup material if available, and avoid improvising a readiness claim.

## Compressed script — approximately 3 minutes

| Time | Action and narration |
| --- | --- |
| 0:00–0:25 | Banner and synthetic/internal limitation. “We are demonstrating an application control sequence using fixed outputs.” |
| 0:25–1:15 | Grounded happy path: permission → authorized metadata → draft → four criteria → separate synthetic Approve. Explain what PASS does and does not mean. |
| 1:15–1:55 | Permission block: retrieval/model not reached. Start a distinct successful run to show safe recovery. |
| 1:55–2:25 | Critical-eval failure: generated BLOCK, approval unavailable. Safe failure is intentional behavior. |
| 2:25–3:00 | Reopen metadata-only history. Close with DRAFT/prospect-ineligible tasks, no holdout validation, and Andrew's pending decision. |

## Architecture one-pager

The approved Python modular monolith uses FastAPI/Jinja presentation, an
application-owned permission and RunService layer, SQLite/FTS retrieval, a model
provider contract, deterministic evaluation, and SQLite minimum provenance.

```text
synthetic context → permission → application-created access scope
  → authorization-filtered source/chunk evidence → fixture draft
  → deterministic critical evaluation → separate eligible synthetic decision
  → metadata-only history
```

BLOCK, UNKNOWN, and unresolved CONDITIONAL permission states fail closed before
protected progression. They are distinct from Legal AI Readiness G1/G2/G3.
Retrieved text and model output cannot grant permissions, change the evaluator,
invoke tools, or approve release. Generated BLOCK permits negative review actions,
not approval. Stored decisions are immutable. Reopening reads metadata without
reconstructing content or executing the chain again.

The provider contract has fixture and approved OpenAI implementations. This demo
uses fixtures only. Provider abstraction is an architectural capability, not
proof of equivalent outcomes across vendors. No DMS, production identity system,
hosted runtime, autonomous tools, or runtime MCP is demonstrated.

## Evaluation/result one-pager

Pack: trade-regulatory-research@1.0.0; six golden cases version 1.0.0. Automated
task: p0-source-grounded-output@1.0.0; rubric:
p0-deterministic-critical-gate@1.0.0. The four CRITICAL criteria are
`authorized-source`, `citation-resolution`, `permission-boundary`, and
`provenance-completeness`. Actual criterion and evaluator versions appear in the
sanitized scenario record.

Two cases expect automated PASS; four expect BLOCK, including the stopped
permission case. A successful negative test means the expected safe failure was
observed. It does not mean the draft passed. The twelve-item rehearsal additionally
covers three synthetic decisions, blocked approval, history/reopen, and rerun.
See scenarios.json for actual results and manifest.json for command outcomes.

Substantive review is a separate four-criterion human rubric: proposition support,
scope discipline, uncertainty handling, draft clarity. All six tasks currently lack
that approval. No protected holdout validation has been performed. CI, golden
comparison, Codex review, synthetic UI decisions, engineering approval, and Gate 5
release authority are separate forms of evidence.

## Talking points and technical/risk FAQ

| Audience / question | Bounded answer |
| --- | --- |
| CIO: What can this demonstrate today? | A local synthetic reference workflow and its tested safe-failure controls. Production integration, operating model, and readiness are outside this candidate. |
| CIO: Can we substitute providers? | The code has a provider contract and approved implementations. This rehearsal does not establish cross-provider equivalence or authorize another provider. |
| CISO: Where does authorization happen? | The application evaluates synthetic permission, creates scope, and filters retrieval before source text enters model context. Tests exercise exact context isolation. Production SSO and DMS enforcement are absent. |
| CISO: Is this secure or certified? | We can identify specific regression-tested boundaries. This is not a certification, penetration-test conclusion, or guarantee. |
| KM: Is the draft correct legal research? | The corpus and tasks are synthetic. Structural source checks cannot supply substantive judgment; qualified review is outstanding. |
| KM: Why can insufficient-source get PASS? | It can satisfy the structural checks while declining an unsupported proposition. PASS does not certify completeness or adequacy. |
| Privacy/risk: What is retained? | The demo retains minimum application metadata and synthetic review decisions. History intentionally does not retain/replay prompt, source, or answer bodies. The collector exports a narrower metadata allowlist. |
| Privacy/risk: Does local execution or store=false prove ZDR? | No. Deployment and request settings do not establish provider retention, privacy, privilege, or confidentiality. Current-source and qualified human review would be required for any separate claim. |
| Legal/risk: Does permission mean legal entitlement or OCG compliance? | No. Synthetic application policy is an engineering exercise, not a legal, ethics, engagement-term, or privilege determination. |
| Engineering: Can the model change its own gate? | No supported path grants it evaluator, permission, tool, or release authority. Negative fixtures exercise this boundary. |
| Engineering: What proves no replay? | Read-phase execution guards plus equal before/after row counts and canonical row hashes for runs, model executions, evaluations, reviews, and child provenance; HTML absence alone is insufficient. |
| Engineering: Can the container reproduce everything? | It is supplemental and lacks the full six-task source-checkout tree. Use the approved source workflow for this pack. |
| Finance: What does the historical live smoke show? | Separate governed execution and telemetry were recorded in DSL-116. Cost was unavailable with pricing evidence missing. It is not this rehearsal, an invoice, a savings result, or a current price claim. |
| Procurement: Are the named vendors partners? | No partnership or endorsement is established by this evidence. API use and architecture references do not establish relationships. |
| Release owner: What remains? | Human substantive eligibility, holdout disposition, claims/visual acceptance, independent/human review evidence, durable promotion, and Andrew's final decision as recorded in the manifest. |
