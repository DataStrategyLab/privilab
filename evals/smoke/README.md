# Offline evaluation smoke harness

`make fixture-smoke` runs five versioned synthetic cases through the production
DSL-113 contracts, evaluators, runner, and critical gate. Expected criterion and
gate values are fixed independently in `cases.json`.

The harness is local and network-free. A passing harness means its declared
checks matched; it is neither a product-quality claim nor human approval.
