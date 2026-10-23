# Documentation

Start with [Getting started](getting-started.md), then
[Reproducibility](reproducibility.md). [Capabilities](capabilities.md) separates
implemented behavior from limits and future work.

Check [local setup qualification](release-status.md#local-setup-qualification)
before execution. No fresh networked native setup is approved; Docker execution
remains held and the default live SDK client is disabled. Public source
inspection/contribution is separate from runtime qualification.

## Implementation

- [Viewing Mermaid diagrams](diagrams/README.md): GitHub and local-preview guidance.
- [System architecture](architecture/system.md): package boundaries, sequence and diagrams.
- [Trust boundaries](architecture/trust-boundaries.md): authorization before context, untrusted text and review authority.
- [Evaluation and scenarios](evaluation.md): structural checks and expected failure cases.
- [Adversarial coverage](architecture/adversarial-coverage.md): existing test/control mapping and exclusions.
- [Local live smoke](architecture/live-eval.md): disabled execution and retained telemetry contracts.
- [Accepted decisions](decisions/README.md): authoritative ADR index.

## Community and release

- [Support](../SUPPORT.md): questions, reporting channels, and support limits.
- [Governance](../GOVERNANCE.md): responsibilities, proposals, and release decisions.
- [Contributors and acknowledgments](../CONTRIBUTORS.md): engineering and historical review credits.
- [Contributing](../CONTRIBUTING.md), [Code of Conduct](../CODE_OF_CONDUCT.md),
  [Security](../SECURITY.md) and [data handling](../DATA_HANDLING.md).
- [License guide](../licenses/README.md) and [third-party notices](../THIRD_PARTY_NOTICES.md).
- [Roadmap](../ROADMAP.md), [changelog](../CHANGELOG.md) and [release status](release-status.md).
- [Review controls](review/code_review.md) and [repository instructions](../AGENTS.md).

## Evidence and examples

- [Synthetic fixtures](fixtures.md) and [evaluation packs](../evals/README.md).
- [Trade/regulatory task pack](../tasks/trade_regulatory/research_v1/README.md).
- [Historical engineering evidence](product/evidence/README.md).
- [Evidence publication proposals](evidence-publication.md): file-by-file
  classification and owner decisions; no captured record is changed or cleared
  for publication by this proposal.

Historical evidence records its own candidate, time and limitations. It is not
current approval merely because it is committed. Pending human/source/security
reviews are tracked in the dated release-status document. Public source publication,
prospect demonstration and production suitability are separate decisions.
