# PriviLAB

**A reference architecture for controlled, permission-aware AI in legal and regulated environments.**

PriviLAB is an implementation-oriented framework for exploring how organizations can build AI workflows that are **grounded, permission-aware, evaluated, human-reviewed, traceable, and portable across model providers**.

Created by **Data Strategy Lab (DSL)**, PriviLAB is designed first for legal technology, where AI systems must operate within demanding data, access, review, and evidentiary boundaries. The same architectural patterns are relevant to adjacent regulated and high-trust environments including government contracting, financial services, insurance, healthcare administration, compliance, investigations, and enterprise knowledge systems.

PriviLAB is not another generic chatbot or thin RAG demo.

Its core question is:

> **How do we build useful AI systems when permission, evidence, evaluation, provenance, and human accountability matter as much as model capability?**

## Why PriviLAB

Large language models are increasingly capable of legal research, document analysis, knowledge retrieval, drafting, extraction, and multi-step reasoning.

But model capability is only one part of a production AI system.

Organizations also need to answer:

- What information is this user actually allowed to retrieve?
- Which client, matter, project, or data restrictions apply?
- Can retrieved material enter model context?
- What evidence supports the generated result?
- Which failures should block release?
- How was the result produced?
- Which model, prompt, sources, permissions, and evaluation criteria were used?
- Who reviewed the result?
- Can the model or infrastructure be replaced without rebuilding the entire application?

PriviLAB treats those questions as **software architecture**, not as after-the-fact governance documentation.

## The PriviLAB control loop

The target PriviLAB workflow is:

```text
User request
    ↓
User / role / context
    ↓
Permission decision
    ↓
Authorization-scoped retrieval
    ↓
Model execution
    ↓
Source-grounded result
    ↓
Task-specific evaluation
    ↓
Critical release gate
    ↓
Human review
    ↓
Release decision
    ↓
Provenance record
```

A credible AI system should demonstrate not only a successful answer, but also safe failure.

PriviLAB is therefore designed to make scenarios such as these first-class:

```text
Unauthorized source
        ↓
      BLOCK

Unknown entitlement
        ↓
   FAIL CLOSED

Unsupported citation
        ↓
   EVAL FAILURE

Critical criterion fails
        ↓
 RELEASE BLOCKED

Human reviewer rejects
        ↓
    NOT RELEASED
```

## What makes PriviLAB different

### Permission before context

Authorization happens before protected source text is permitted to leave the retrieval layer and enter downstream model context.

This makes permission enforcement part of the retrieval contract rather than an instruction placed inside a prompt.

### Evaluation as product infrastructure

PriviLAB is being designed around task-specific evaluation rather than generic model benchmarks.

The evaluation layer is intended to support:

- versioned criteria;
- deterministic checks where possible;
- critical criteria;
- citation and grounding validation;
- permission and isolation tests;
- model-assisted evaluation where appropriate;
- human review;
- regression testing.

A model that produces fluent output but fails a critical requirement should not automatically pass.

### Provenance by design

PriviLAB's architecture treats provenance as a core system capability.

A workflow should be able to reconstruct relevant information such as:

```text
run
workflow + version
user / role / context
permission decision
retrieved source IDs
model / provider / version
prompt or agent version
evaluation criteria
criterion results
human review
release decision
timestamps
latency / cost where available
configuration version
```

The objective is traceability without indiscriminately retaining sensitive content.

### Model portability

PriviLAB separates model execution behind provider contracts.

The architecture is intended to support experimentation across:

- frontier managed models;
- hosted open-weight models;
- dedicated model deployments;
- self-hosted models;
- workflow-specific fine-tunes;
- multi-model architectures.

Model choice should be driven by workflow evidence rather than platform lock-in.

### Human accountability

PriviLAB does not assume that an AI system should independently release consequential work.

Human review and release authority are explicit parts of the architecture.

## Current implementation

PriviLAB is under active development.

The current implementation includes foundational components for the controlled workflow architecture, including:

- typed context and permission contracts;
- executable access-scope boundaries;
- authorization-scoped SQLite / FTS5 retrieval;
- fail-closed permission behavior;
- deterministic model-provider interfaces;
- `FixtureModelProvider` for safe model-independent development;
- approved `OpenAIProvider` for `gpt-5.6-terra`, verified with offline SDK tests;
- stable source and chunk identifiers;
- synthetic request, permission, corpus, and model-output fixtures;
- source and license metadata validation;
- authorization and cross-context isolation tests;
- reproducible offline verification;
- FastAPI / Jinja preview infrastructure.

Development began with deterministic fixtures and controlled local behavior before introducing the approved OpenAI adapter. The preview and CI remain fixture-based. DSL-116 adds separately gated local `make eval-live` execution with reconstructable usage, latency, and conditional cost evidence; see the [live smoke instructions](docs/architecture/live-eval.md).

This allows security boundaries, retrieval behavior, tests, and evaluation contracts to be exercised without requiring production credentials or sensitive data.

## Architecture

PriviLAB currently uses a small Python modular-monolith architecture:

```text
┌─────────────────────────────────────────────┐
│                 Web / API                   │
│         FastAPI + Jinja + minimal JS        │
└──────────────────────┬──────────────────────┘
                       │
┌──────────────────────▼──────────────────────┐
│              Application Layer              │
│     orchestration / workflow boundaries     │
└─────────────┬─────────────────┬─────────────┘
              │                 │
┌─────────────▼──────┐   ┌──────▼────────────┐
│   Permission /     │   │ Model Provider    │
│   Domain Contracts │   │ Abstraction       │
└─────────────┬──────┘   └──────┬────────────┘
              │                 │
┌─────────────▼─────────────────▼─────────────┐
│                  Adapters                    │
│ retrieval │ models │ persistence │ future   │
└─────────────┬───────────────────────────────┘
              │
┌─────────────▼───────────────────────────────┐
│      SQLite / FTS5 controlled corpus       │
└─────────────────────────────────────────────┘

            + evaluation layer
            + provenance layer
            + human release gate
```

The architecture intentionally avoids introducing a generalized autonomous-agent framework before the core permission, retrieval, evaluation, provenance, and review boundaries are proven.

See:

- [`docs/architecture/system.md`](docs/architecture/system.md)
- [`docs/architecture/trust-boundaries.md`](docs/architecture/trust-boundaries.md)
- [`docs/decisions/`](docs/decisions/)
- [`AGENTS.md`](AGENTS.md)

## Quick start

### Prerequisites

PriviLAB currently targets:

- Python 3.13
- macOS or Linux
- POSIX shell
- Git
- `make`
- `curl`
- `tar`
- a SHA-256 utility
- Docker for the optional container preview

### Bootstrap

```sh
./scripts/bootstrap.sh
```

Bootstrap is the only normal step permitted to download the pinned toolchain and locked Python dependencies.

### Verify

```sh
make ci
```

After bootstrap, `make ci` is designed to be:

```text
secret-free
network-free
reproducible
usable locally and in CI
```

The verification contract includes repository, fixture, license, software, and security checks appropriate to the currently implemented P0 capabilities.

### Run the local preview

```sh
make preview
```

Then open <http://127.0.0.1:8000>.

The preview completes a controlled fixture run, records its terminal provenance,
runs the existing DSL-113 deterministic evaluation, and stores one immutable
metadata snapshot. Human review remains a separate, explicit action.

The **PriviLAB Reference Demo** uses a compact synthetic-scenario selector and an
expandable guide. **Run scenario** opens the run summary, context, permission,
authorized source metadata, draft, evaluation, human review, and traceability.
Technical identifiers and evidence remain inspectable through disclosure controls.
The interface, stylesheet, and approved DSL logo are served locally without a
frontend build step or required JavaScript.

Walk through these scenarios:

1. **Standard synthetic researcher**: inspect the transient **Draft result**,
   evaluation criteria and PASS gate. The human decision starts PENDING; choose
   **Approve**, **Reject**, or **Request revision**.
2. **Blocked researcher role**, **Missing workflow context**, or **Unresolved
   permission condition**: BLOCK, UNKNOWN,
   or unresolved CONDITIONAL stops progression before retrieval or model calls.
   These runs are NOT REVIEWABLE.
3. **Critical citation failure**: inspect the recorded BLOCK. Approval is disabled;
   REJECT and REQUEST_REVISION remain available.
4. **Malicious retrieved source**: the governed synthetic injection text reaches
   authorized model context. Its instructions cannot broaden source access,
   change the rubric/gate, invoke tools, or create a human decision. The existing
   citation-failure model fixture produces BLOCK. HTML shows source/chunk metadata
   and an untrusted-fixture label, never the retrieved text. This demonstrates
   deterministic controls, not general live-model injection resistance.
5. Use the **Trade / regulatory** choices to inspect all six DSL-117 scenarios,
   including insufficient evidence, missing citations, and the citation challenge.
   These remain internal DRAFT fixtures requiring the local task-pack checkout.
6. Open **Recent history**, stop and restart `make preview`, and reopen a run.
   History lists the newest 25 finalized runs by completion time and run ID,
   descending; older run URLs still work. Reopening and reviewing never rerun
   generation, retrieval or evaluation.

Original-run **Source references** disclose only citation pairs present in the
run's authorized source/chunk metadata. Other pairs display **Reference unavailable**;
their identifiers are withheld. Evaluation still receives the unchanged result.
Neither displaying a citation nor an automated PASS supplies human approval.
Reopened runs retain neither generated answer text nor draft citations.

The [demo UI verification aid](docs/product/evidence/demo-ui-claims-checklist.md)
maps claims, accessibility-oriented checks, and acceptance evidence to the code.

`synthetic-local-reviewer` is a fixed **local demo identity**, not authenticated
attribution. Each run permits one immutable decision. REQUEST_REVISION creates no
revision workflow or lineage; another execution gets an independent run ID. No
decision constitutes release. Simultaneous valid submissions produce one stored
decision and one conflict response.

Non-secret preview settings (see `.env.example`):

| Setting | Default / behavior |
| --- | --- |
| `PRIVILAB_PREVIEW_DB` | Source-checkout `.local/preview/provenance.sqlite3`; optional absolute database path. |
| `PRIVILAB_PREVIEW_CORPUS_ROOT` | Source-checkout `fixtures/corpus/`, anchored to the resolved location of `config.py`; optional non-empty absolute corpus path. |

Neither path depends on process CWD. Browser requests cannot set either path.
Tests can inject absolute paths through `Settings`. Configuration loading does
not create a database or execute fixtures. The malicious scenario reads its
injection and trade-notice records from the configured canonical corpus using
manifest, path-confinement, payload and hash checks. Missing/invalid assets fail
safely; there is no fallback discovery or second packaged corpus.

SQLite retains terminal provenance, evaluation metadata and the explicit human
decision. It retains no answer text, task/prompt/query text, model requests,
retrieved text, reviewer notes or raw exceptions. Generated answers appear only
on the original execution response; reopening is metadata-only. The FTS index
remains transient. Evaluation execution or persistence failure leaves the
terminal run visible but NOT REVIEWABLE, without manufactured evidence.

This version requires a fresh evidence schema. Existing incompatible databases
are rejected unchanged: there is no migration, repair or automatic deletion.
Choose a new absolute `PRIVILAB_PREVIEW_DB` path when testing an older checkout's
database. Strict metadata validation detects invalid records; it does not
authenticate a deliberately forged local database. Generated database files stay
untracked.

An optional container workflow is also available:

```sh
make container-build
make container-preview
```

The image copies only the existing `fixtures/corpus` subtree and explicitly sets
`PRIVILAB_PREVIEW_CORPUS_ROOT=/app/fixtures/corpus` and
`PRIVILAB_PREVIEW_DB=/app/.local/preview/provenance.sqlite3`. The existing container
command removes its container on exit, so its local database is discarded then;
use the source-checkout workflow above for the restart/history walkthrough.
Docker validation is required before DSL-114 completion.

## Permission-aware retrieval

One of PriviLAB's foundational design rules is:

> **Unauthorized material must not enter retrieval results and must not reach model context.**

Retrieval therefore requires an application-authorized `AccessScope`.

Conceptually:

```text
context
    ↓
permission evaluation
    ↓
AccessScope
    ↓
retrieval provider
    ↓
authorized chunks only
```

The retrieval layer is designed to fail closed when entitlement information is missing or invalid.

The current SQLite / FTS5 implementation also returns stable source and chunk identifiers so later evaluation and provenance layers can reason about exactly which evidence participated in a run.

## Safe data by default

The reusable PriviLAB repository is designed around:

- public information;
- repository-authored synthetic data;
- anonymized or properly redacted material;
- properly licensed materials.

Fixtures are versioned and registered with provenance and license metadata.

PriviLAB is **not** intended to become a repository for client matters, privileged material, work product, identifiable outside-counsel restrictions, restricted legal databases, credentials, or sensitive production data.

See [`DATA_HANDLING.md`](DATA_HANDLING.md).

## Model providers

PriviLAB uses provider abstractions so workflow logic is not tightly coupled to one model platform.

### Deterministic provider

The current `FixtureModelProvider` enables the system to develop and test model-facing behavior deterministically.

This is intentional.

The fixture path exercises:

```text
permissions
retrieval boundaries
schemas
citations
failure handling
tests
evaluation interfaces
```

without making network access or model behavior a prerequisite.

### Approved OpenAI provider

`OpenAIProvider` uses the official OpenAI Python SDK and Responses API for exactly
`gpt-5.6-terra`. `RunService.from_openai(...)` constructs the provider and governed
configuration internally, preserving permission evaluation and scoped retrieval
before model execution. The factory accepts an `OpenAIProviderConfig` from
`privilab.adapters.models.openai`; it does not accept arbitrary provider identities,
credentials, or alternate endpoints. Fixture preview behavior remains unchanged.

Each request explicitly sets `store=False`, `stream=False`, `background=False`,
`tools=[]`, `tool_choice="none"`, and `truncation="disabled"`. Only the task and
already-authorized chunks enter model input alongside fixed instructions and the
research-result schema. `store=False` is request configuration, not a Zero Data
Retention, privacy, confidentiality, privilege, compliance, or security guarantee.

Credentials come from `OPENAI_API_KEY` only when execution begins. The destination
is fixed to `https://api.openai.com/v1`; `OPENAI_BASE_URL` cannot redirect it.
The default SDK transport timeout is 30 seconds (allowed: 1–120), with SDK retries
disabled. Application retries are limited to two (allowed: 0–2), using 0.5/1-second
backoff and a configurable maximum delay of five seconds (allowed: 1–5). Valid
server retry delays are minimums; delays above the bound fail safely. These are
transport timeouts and bounded retry settings, not a total wall-clock deadline.
Billing, credit, spend/usage-limit, and semantic output failures are not retried.

`generate(request)` still returns `ResearchResult`. The adapter-specific
`generate_with_usage(request)` returns an immutable `OpenAIGeneration` pairing
that result with provider-reported token counts, including cache reads, cache
writes, and reasoning. Missing counts remain `None`. SDK wire usage is validated
before SDK numeric coercion; raw payloads are not retained or persisted. There is
no mutable last-call state. `RunOutcome` and provenance schemas are unchanged.

Existing provenance records provider/adapter identity, the configured model alias,
SDK/request/schema versions, and timeout/retry settings. The alias is not a pinned
dated model snapshot. DSL-116 owns live smoke execution and usage, latency,
pricing, and cost integration/persistence. DSL-115 tests require neither a live
OpenAI call nor API credentials; no live-execution claim is made here.

### Open-weight models and Fireworks AI

A planned research and implementation track will evaluate [Fireworks AI](https://fireworks.ai/) for hosted open-weight inference, model evaluation, dedicated deployments, and workflow-specific fine-tuning.

Potential PriviLAB experiments include:

```text
baseline open-weight model
        ↓
PriviLAB workflow evals
        ↓
failure analysis
        ↓
supervised or reinforcement fine-tuning
        ↓
re-evaluation
        ↓
deployment through the same provider contract
```

This creates an opportunity to evaluate whether smaller or specialized open-weight models can perform particular legal or regulated-industry tasks efficiently while preserving PriviLAB's permission, evaluation, provenance, and human-review controls.

Where licensing, deployment requirements, and benchmark evidence support it, this may include evaluation of U.S.-developed open-weight models.

Fireworks integration and model fine-tuning are **roadmap capabilities, not current production features**.

## Evaluation

Legal AI quality cannot be reduced to whether an answer sounds convincing.

PriviLAB's evaluation architecture is intended to examine behavior at the task and criterion level.

Example:

```text
Research task
│
├── Did the system use only authorized sources?
├── Do cited sources exist?
├── Does each source support the relevant proposition?
├── Were required issues addressed?
├── Were unsupported conclusions avoided?
├── Did the requested output structure appear?
└── Did all critical requirements pass?
```

Some criteria may be informational or quality-scored.

Others can be designated **critical gates**.

```text
Overall quality:       92%
Critical criterion:    FAIL

Release decision:      BLOCK
```

This distinction is important for workflows where one serious failure should not be averaged away by otherwise strong performance.

## PriviLAB and the legal-AI evaluation ecosystem

PriviLAB is complementary to emerging open legal-AI benchmarking projects such as [Harvey's Legal Agent Benchmark (LAB)](https://github.com/harveyai/harvey-labs).

LAB focuses on evaluating agents against realistic legal tasks and structured rubrics.

PriviLAB explores a different but related problem:

> **How should the surrounding application control what an AI workflow may access, how it retrieves evidence, how its work is evaluated, who may release it, and how the run can later be reconstructed?**

The projects can therefore be useful together.

For example, future PriviLAB research may evaluate compatible public benchmark tasks or task-design patterns while preserving PriviLAB's own permission, provenance, deployment, and release architecture.

PriviLAB is an independent Data Strategy Lab project and is not affiliated with or endorsed by Harvey.

## From legal AI to regulated AI

Legal services provide a demanding proving ground for controlled AI because the work often combines sensitive information, complex permissions, evidence requirements, professional review, and high consequences for error.

But the same architectural problem appears elsewhere.

### Law firms and legal departments

Potential patterns include:

```text
knowledge retrieval
regulatory research
litigation support
investigations
document analysis
contract workflows
knowledge management
information governance
```

### Government contractors and public-sector environments

The same framework can inform experimentation around:

```text
role-restricted knowledge
proposal and capture support
controlled document retrieval
policy and regulatory analysis
contract administration
human-reviewed decision support
```

Actual deployment would require controls appropriate to the applicable system, contract, information classification, and authorization regime.

### Other regulated industries

PriviLAB patterns can also apply to systems where:

```text
permission
+ evidence
+ evaluation
+ human accountability
+ provenance
```

are fundamental requirements rather than optional enterprise features.

## Design principles

### Permission before capability

A system being technically capable of performing an action does not mean that the action is permitted.

### Authorization before context

Protected information should be filtered before it reaches model context.

### Unknown fails safely

Missing permission evidence should not silently become permission.

### Ground outputs in identifiable sources

Generated claims should be traceable to supporting evidence when the workflow requires grounding.

### Evaluate before release

Task-specific quality criteria should be executable wherever practical.

### Human review remains explicit

AI evaluation and automated tests support human judgment rather than silently replacing accountable review.

### Provenance without indiscriminate logging

Capture enough information to reconstruct important system behavior without assuming that storing more sensitive content is safer.

### Provider portability

Models are replaceable components.

### Safe failure is a feature

Blocking, escalation, abstention, and conditional outcomes are expected system behaviors.

### Reversibility matters

Models, providers, connectors, permissions, prompts, and releases should be replaceable or reversible where practical.

## Roadmap

PriviLAB is being developed incrementally rather than attempting to build a complete enterprise legal-AI platform in one release.

The broader architecture is expected to explore:

```text
Controlled request context
        ↓
Permission-aware retrieval
        ↓
Model-provider abstraction
        ↓
Grounded generation
        ↓
Task-specific evals
        ↓
Critical release gates
        ↓
Human review
        ↓
Minimum viable provenance
        ↓
────────────────────────────
Future extension points
────────────────────────────
Fireworks / open-weight provider
workflow-specific fine-tuning
expanded legal eval packs
DMS / enterprise knowledge connectors
iManage / NetDocuments patterns
private deployment patterns
additional regulated-industry examples
```

Each capability is intended to be introduced behind explicit requirements, architecture decisions, tests, and review rather than treated as automatically approved because a vendor or model supports it.

## What PriviLAB is not

PriviLAB is not:

- a law firm;
- legal advice;
- an ethics opinion;
- a privilege determination;
- a compliance determination;
- a cybersecurity certification;
- a representation that any specific AI deployment is appropriate for a particular client, matter, organization, or jurisdiction;
- a guarantee of confidentiality, privilege, accuracy, security, or zero hallucinations;
- a claim that an AI benchmark establishes production fitness.

PriviLAB demonstrates technical controls and implementation patterns.

Organizations remain responsible for determining the legal, contractual, security, professional, operational, and policy requirements applicable to their own deployments.

## Repository philosophy

PriviLAB is developed using an evidence-driven engineering process:

```text
requirement
    ↓
architecture decision when needed
    ↓
bounded engineering issue
    ↓
implementation
    ↓
tests + evals
    ↓
independent review
    ↓
pull request
    ↓
human merge decision
```

AI-assisted development is welcome.

AI-generated code receives the same architectural, security, testing, data, licensing, and review requirements as human-generated code.

See [`AGENTS.md`](AGENTS.md), [`CONTRIBUTING.md`](CONTRIBUTING.md), and [`docs/review/code_review.md`](docs/review/code_review.md).

## Contributing

PriviLAB is intended to become a useful implementation reference for engineers, legal technologists, AI researchers, security practitioners, knowledge-management teams, and organizations building controlled AI systems.

Useful contribution areas are expected to include:

- permission and entitlement models;
- retrieval providers;
- model-provider adapters;
- legal and regulated-industry eval tasks;
- citation and grounding checks;
- provenance patterns;
- adversarial and isolation tests;
- public or synthetic example workflows;
- deployment blueprints;
- documentation;
- security improvements.

Before contributing, read:

- [`CONTRIBUTING.md`](CONTRIBUTING.md)
- [`AGENTS.md`](AGENTS.md)
- [`DATA_HANDLING.md`](DATA_HANDLING.md)
- [`SECURITY.md`](SECURITY.md)
- [`docs/architecture/system.md`](docs/architecture/system.md)

All contributed data, fixtures, benchmarks, and third-party assets must have a documented source and permitted-use basis.

## Security

Authorization and isolation failures are treated as defects.

Please do not disclose suspected vulnerabilities through a public issue.

Follow the reporting process described in [`SECURITY.md`](SECURITY.md).

## Open-source status and licensing

PriviLAB is currently under active development and is being prepared for a future public open-source release.

The public licensing model and final open-source boundary must be established before release.

Until an explicit repository license is published, do not assume that the absence of a license grants permission to copy, modify, redistribute, or commercially reuse repository contents.

Third-party dependencies, datasets, benchmark materials, and fixtures may have their own licenses or usage conditions and are tracked separately where applicable.

## Built by Data Strategy Lab

**Data Strategy Lab LLC** builds AI, software, data, and implementation systems for organizations operating in complex or high-trust environments.

PriviLAB is DSL's reference implementation for exploring a simple idea:

> **The next generation of enterprise AI will not be defined only by which model is smartest. It will be defined by how effectively organizations can control what AI may access, verify what it produces, understand how it got there, and keep accountable humans in the loop.**

## Project status

| | |
|---|---|
| **Status** | Active development / pre-release |
| **Primary implementation** | Python 3.13 |
| **Application** | FastAPI + Jinja |
| **Retrieval** | SQLite + FTS5 |
| **Verification** | Reproducible `make ci` contract |
| **Data posture** | Public / synthetic / anonymized / redacted / properly licensed materials only |
| **Current model path** | Fixture preview; approved OpenAI adapter verified offline |
| **Planned model paths** | Managed and open-weight providers following explicit architecture and release gates |

---

**PriviLAB is an implementation reference, not a certification or legal determination.**
