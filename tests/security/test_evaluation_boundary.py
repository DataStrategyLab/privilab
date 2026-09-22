from __future__ import annotations

from dataclasses import replace

from privilab.domain import CitationReference, ResearchResult
from privilab.evals import EvaluationInput, evaluate
from privilab.evals.smoke import _generated_input


def test_evaluation_result_retains_no_untrusted_answer_or_source_text() -> None:
    marker = "UNTRUSTED_SOURCE_OR_ANSWER_TEXT_MUST_NOT_APPEAR"
    input_value = _generated_input(
        CitationReference("synthetic-source", "synthetic-chunk")
    )
    outcome = replace(
        input_value.outcome,
        result=ResearchResult(
            marker,
            (CitationReference("synthetic-source", "synthetic-chunk"),),
        ),
    )
    result = evaluate(EvaluationInput(outcome, input_value.provenance))
    assert marker not in repr(result)
    assert all(marker not in repr(criterion.evidence) for criterion in result.criteria)
