# Golden evaluation evidence

`trade_regulatory_v1/cases.json` contains six versioned synthetic DSL-117 cases.
Each references one domain task/version and independently declares expected run,
criterion, gate, review-eligibility, and configuration-identity outcomes.

Run `make golden-eval`; `make ci` includes the same canonical validation and governed
fixture execution. These cases add evidence alongside the unchanged smoke pack.
They do not change the protected holdout or supply substantive human approval.

See `tasks/trade_regulatory/research_v1/README.md` for scenarios, source mappings,
review status, preview instructions, identity binding, and limitations.
