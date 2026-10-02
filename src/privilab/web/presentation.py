"""Repository-authored display copy; never workflow or evaluation authority.

Scenario summaries describe the bounded exercises without loading task artifacts.
The selected task's actual text is supplied only by its existing execution path.
"""

SCENARIO_COPY = {
    "standard": (
        "Standard synthetic researcher",
        "Follow an allowed request through evidence, draft, evaluation, and review.",
        "Summarize only the supplied synthetic chunks.",
    ),
    "blocked-role": (
        "Blocked researcher role",
        "See protected progression stop at the permission decision.",
        "Attempt the synthetic summary with a blocked role.",
    ),
    "missing-workflow": (
        "Missing workflow context",
        "See an UNKNOWN permission decision fail closed.",
        "Attempt the synthetic summary without a workflow.",
    ),
    "conditional-role": (
        "Unresolved permission condition",
        "See a CONDITIONAL decision stop while a condition is unresolved.",
        "Attempt the synthetic summary with an unresolved condition.",
    ),
    "critical-citation-failure": (
        "Critical citation failure",
        "Inspect a draft whose citation fails the automated critical gate.",
        "Summarize synthetic chunks with a deliberately invalid fixture citation.",
    ),
    "malicious-source": (
        "Malicious retrieved source",
        "Inspect the boundary between untrusted source data and application controls.",
        "Exercise the synthetic instruction-attack and citation-failure fixture.",
    ),
    "trade-regulatory.grounded-happy-path": (
        "Trade / regulatory — grounded notice",
        "Follow a bounded source-based draft into separate human review.",
        "Describe the synthetic trade notice and its stated purpose with a citation.",
    ),
    "trade-regulatory.insufficient-source": (
        "Trade / regulatory — insufficient source",
        "See a draft acknowledge that the supplied evidence is insufficient.",
        "Assess whether the supplied source establishes a requirement or penalty.",
    ),
    "trade-regulatory.permission-block": (
        "Trade / regulatory — permission block",
        "See a task stop before retrieval or generation.",
        "Describe the synthetic notice only if permission allows progression.",
    ),
    "trade-regulatory.critical-eval-failure": (
        "Trade / regulatory — missing citation",
        "See a missing required citation block approval.",
        "Describe the notice; the negative fixture deliberately omits its citation.",
    ),
    "trade-regulatory.citation-grounding-challenge": (
        "Trade / regulatory — citation challenge",
        "See a citation to a missing chunk fail the critical gate.",
        "Describe the notice; the negative fixture deliberately names a missing chunk.",
    ),
    "trade-regulatory.malicious-source-injection": (
        "Trade / regulatory — instruction attack",
        "See untrusted instructions remain separate from permission and review.",
        "Inspect a synthetic instruction-attack source as untrusted data.",
    ),
}

CONTEXT_LABELS = {
    "synthetic-user-001": "Researcher 001",
    "synthetic-researcher": "Researcher",
    "synthetic-blocked": "Blocked researcher role",
    "synthetic-conditional": "Conditional researcher role",
    "synthetic-client-001": "Client 001",
    "synthetic-matter-001": "Matter 001",
    "synthetic-workflow-001": "Research workflow 001",
}

CRITERION_LABELS = {
    "permission-boundary": "Permission boundary",
    "authorized-source": "Sources in the run context",
    "citation-resolution": "Citation resolution",
    "provenance-completeness": "Provenance completeness",
}

REASON_LABELS = {
    "PERMISSION_BOUNDARY_RESPECTED": "Permission boundary respected.",
    "PERMISSION_BOUNDARY_VIOLATION": "Permission boundary violation recorded.",
    "SOURCES_IN_RUN_CONTEXT": "Cited sources belong to the run context.",
    "SOURCE_NOT_IN_RUN_CONTEXT": "A cited source is outside the run context.",
    "CITATIONS_RESOLVED": "Citation references resolve within the run context.",
    "CITATION_NOT_IN_RUN_CONTEXT": "A citation does not resolve in the run context.",
    "CITATION_REQUIRED": "A required citation is missing.",
    "GENERATED_OUTPUT_UNAVAILABLE": "Generated output is unavailable.",
    "PROVENANCE_COMPLETE": "Required provenance metadata is present.",
    "PROVENANCE_INCOMPLETE": "Required provenance metadata is incomplete.",
    "EVALUATOR_EXECUTION_ERROR": "The evaluator could not complete.",
    "EVALUATOR_RESULT_MALFORMED": "Evaluator evidence could not be accepted.",
    "INPUT_MISSING_PROVENANCE": "Evaluation input lacks required provenance.",
    "INPUT_INCONSISTENT": "Evaluation input is inconsistent.",
    "INPUT_MALFORMED": "Evaluation input could not be accepted.",
}
