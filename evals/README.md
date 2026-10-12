# Evaluation packs

Normal evaluation is deterministic and offline. Run `make ci` for complete
verification or `make golden-eval` for supplemental golden output inspection.

- [Smoke](smoke/README.md): bounded deterministic fixture checks.
- [Golden](golden/README.md): registered synthetic expected outcomes.
- [Candidates](candidates/README.md): candidate-specific evaluation organization.
- [Holdout](holdout/README.md): protected-holdout placeholder, not performed validation.
- [Trade/regulatory tasks](../tasks/trade_regulatory/research_v1/README.md).

See [Evaluation and scenarios](../docs/evaluation.md). Golden fixtures are not a
protected holdout. Automated PASS/BLOCK does not substitute for qualified domain
review, authenticated review authority or a release decision. Paid/live calls
remain outside CI and require the separate local live-smoke workflow.
