# PriviLAB Public Roadmap

**Status: pre-release / active development**

PriviLAB is Data Strategy Lab's reference implementation for controlled, permission-aware AI workflows in legal and other regulated or high-trust environments.

This roadmap communicates direction, not commitments. Planned capabilities are not represented as shipped, production-ready, approved for client data, or appropriate for any specific deployment.

## Current foundation

The current implementation is focused on proving the control boundaries before expanding model or integration complexity:

- typed request, context, and permission contracts;
- fail-closed permission decisions;
- authorization-scoped SQLite / FTS5 retrieval;
- stable source and chunk identifiers;
- deterministic model-provider contracts and `FixtureModelProvider`;
- synthetic/public fixture and license controls;
- authorization and isolation tests;
- reproducible local verification;
- FastAPI / Jinja preview infrastructure.

## Next: complete the controlled vertical slice

The near-term objective is one end-to-end workflow that can demonstrate both successful execution and safe failure:

```text
request
→ permission
→ authorized retrieval
→ model result
→ grounding
→ evaluation
→ critical gate
→ human review
→ provenance
```

Near-term work includes:

- workflow orchestration and provenance persistence;
- versioned task-specific evaluation;
- grounding and citation checks;
- critical release gates;
- human approve / reject / revise flow;
- restart-persistent run history;
- adversarial, permission-block, malicious-source, and regression scenarios;
- a concise executable demo using approved public or synthetic materials.

## Model-provider expansion

After the deterministic control path is accepted, PriviLAB expects to evaluate live providers behind the existing provider abstraction.

Potential work includes:

- managed frontier-model integration;
- OpenAI provider support;
- Fireworks AI and hosted open-weight model experiments;
- provider/model/version metadata in provenance;
- task-level quality, latency, and cost comparisons.

Provider inclusion does not imply endorsement, partnership, certification, or permanent architectural preference.

## Open-weight models and fine-tuning

PriviLAB plans to investigate whether open-weight models can be specialized for bounded legal or regulated-industry workflows.

Potential experiments include:

- baseline open-weight evaluation;
- workflow-specific supervised fine-tuning;
- reinforcement fine-tuning where justified;
- controlled comparison against stronger general models;
- evaluation of deployment, licensing, quality, latency, and economics.

Training will be pursued only where task-specific evaluation evidence supports it. No fine-tuned PriviLAB model is currently represented as production-ready.

## Evaluation and provenance

PriviLAB treats evaluation and provenance as product infrastructure.

Planned expansion includes:

- reusable public/synthetic task schemas;
- criterion-level evaluation reports;
- citation and grounding checks;
- permission-boundary and isolation evals;
- prompt-injection and malicious-source cases;
- safe-failure tests;
- model/provider comparison utilities;
- reconstruction of workflow version, permissions, sources, model/provider, eval results, reviewer, release decision, and relevant runtime metadata.

Automated evaluation supports human judgment; it does not replace accountable review.

## Enterprise knowledge and deployment patterns

Later research may explore:

- iManage and NetDocuments integration patterns;
- enterprise knowledge and document repositories;
- permission-aware secondary indexing;
- carefully scoped API or MCP integration patterns;
- managed API, dedicated inference, customer-VPC, and self-hosted deployment options.

Any real integration must preserve the authoritative source system's identity, permission, information-barrier, contractual, and data-handling constraints.

## Adjacent regulated environments

Legal technology is the first proving ground. Future public examples may explore the same control patterns for:

- government contracting;
- compliance;
- investigations;
- financial services;
- insurance;
- healthcare administration;
- regulated enterprise knowledge.

## Community priorities

As PriviLAB approaches public release, useful contribution areas include:

- permission and entitlement models;
- retrieval and model-provider adapters;
- evaluation tasks and adversarial tests;
- grounding and citation validation;
- provenance patterns;
- safe public/synthetic example workflows;
- deployment blueprints;
- documentation and security improvements.

## Out of scope for the near term

PriviLAB is not currently being developed as:

- a general-purpose autonomous-agent platform;
- a hosted legal-research SaaS;
- a replacement document-management system;
- an automated legal decision-maker;
- a privilege, ethics, security, or compliance certification system;
- a repository for live client matter data.

## Release direction

The working public-release direction is:

- **License:** Apache License 2.0
- **Initial public version:** `v0.1.0`
- **Release designation:** Developer Preview
- **Status:** pre-release until Data Strategy Lab completes release, security, licensing, data, trademark, and claims review and the Product Owner explicitly approves publication.
