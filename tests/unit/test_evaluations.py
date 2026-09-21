from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from privilab.domain import CitationReference, PermissionResult, PermissionState
from privilab.evals import evaluators
from privilab.evals.contracts import (
    CriterionCriticality,
    CriterionDefinition,
    CriterionResult,
    CriterionStatus,
    CriticalGateResult,
    EvaluationEvidence,
    EvaluationInput,
    EvaluationResult,
    EvaluatorKind,
    GateStatus,
    ReasonCode,
    TaskDefinition,
    p0_task_definition,
)
from privilab.evals.runner import calculate_gate, evaluate
from privilab.evals.smoke import _generated_input, _stopped_input, run_smoke

ROOT = Path(__file__).parents[2]


def _criterion(result: EvaluationResult, criterion_id: str) -> CriterionResult:
    return next(item for item in result.criteria if item.criterion_id == criterion_id)


def _result(
    definition: CriterionDefinition,
    status: CriterionStatus,
    input_value: EvaluationInput,
) -> CriterionResult:
    reason_code = {
        EvaluatorKind.PERMISSION_BOUNDARY: {
            CriterionStatus.PASS: ReasonCode.PERMISSION_BOUNDARY_RESPECTED,
            CriterionStatus.FAIL: ReasonCode.PERMISSION_BOUNDARY_VIOLATION,
        },
        EvaluatorKind.AUTHORIZED_SOURCE: {
            CriterionStatus.PASS: ReasonCode.SOURCES_IN_RUN_CONTEXT,
            CriterionStatus.FAIL: ReasonCode.SOURCE_NOT_IN_RUN_CONTEXT,
            CriterionStatus.UNKNOWN: ReasonCode.GENERATED_OUTPUT_UNAVAILABLE,
        },
        EvaluatorKind.CITATION_RESOLUTION: {
            CriterionStatus.PASS: ReasonCode.CITATIONS_RESOLVED,
            CriterionStatus.FAIL: ReasonCode.CITATION_NOT_IN_RUN_CONTEXT,
            CriterionStatus.UNKNOWN: ReasonCode.GENERATED_OUTPUT_UNAVAILABLE,
        },
        EvaluatorKind.PROVENANCE_COMPLETENESS: {
            CriterionStatus.PASS: ReasonCode.PROVENANCE_COMPLETE,
            CriterionStatus.FAIL: ReasonCode.PROVENANCE_INCOMPLETE,
        },
    }.get(definition.evaluator_kind, {}).get(
        status, ReasonCode.EVALUATOR_EXECUTION_ERROR
    )
    return CriterionResult(
        criterion_id=definition.criterion_id,
        criterion_version=definition.criterion_version,
        evaluator_kind=definition.evaluator_kind,
        evaluator_version=definition.evaluator_version,
        criticality=definition.criticality,
        status=status,
        evidence=EvaluationEvidence(
            (reason_code,),
            0
            if input_value.provenance is None
            else len(input_value.provenance.sources),
            0
            if input_value.outcome.result is None
            else len(input_value.outcome.result.citations),
        ),
    )


def _task_with_optional_criterion() -> tuple[TaskDefinition, CriterionDefinition]:
    task = p0_task_definition()
    optional = CriterionDefinition(
        "optional-source-check",
        "1.0.0",
        EvaluatorKind.AUTHORIZED_SOURCE,
        "1.0.0",
        CriterionCriticality.NON_CRITICAL,
    )
    return (
        replace(
            task,
            rubric=replace(task.rubric, criteria=task.rubric.criteria + (optional,)),
        ),
        optional,
    )


def _passing_results(
    task: TaskDefinition, input_value: EvaluationInput
) -> tuple[CriterionResult, ...]:
    return tuple(
        _result(definition, CriterionStatus.PASS, input_value)
        for definition in task.rubric.criteria
    )


def test_governed_task_identity_and_json_are_preserved() -> None:
    task = TaskDefinition.from_json(
        (ROOT / "evals/smoke/rubric.json").read_text(encoding="utf-8")
    )
    assert task == p0_task_definition()
    result = evaluate(
        _generated_input(CitationReference("synthetic-source", "synthetic-chunk")),
        task,
    )
    assert (result.task_id, result.task_version) == (task.task_id, task.task_version)
    assert (result.rubric_id, result.rubric_version) == (
        task.rubric.rubric_id,
        task.rubric.rubric_version,
    )
    assert [
        (item.criterion_id, item.criterion_version) for item in result.criteria
    ] == [
        (item.criterion_id, item.criterion_version)
        for item in sorted(task.rubric.criteria, key=lambda item: item.criterion_id)
    ]


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        '{"task_id":"a","task_id":"b","task_version":"1","rubric":{}}',
        '{"task_id":"a","task_version":"1","rubric":{"rubric_id":"r","rubric_version":"1","criteria":[]}}',
        '{"task_id":"a","task_version":"1","rubric":{"rubric_id":"r","rubric_version":"1","criteria":[{"criterion_id":"x","criterion_version":"1","evaluator_kind":"unknown","evaluator_version":"1.0.0","criticality":"CRITICAL"}]}}',
    ],
)
def test_task_contract_rejects_malformed_and_unsupported_serialized_values(
    payload: str,
) -> None:
    with pytest.raises(ValueError):
        TaskDefinition.from_json(payload)


def test_rubric_rejects_duplicate_criterion_id_with_different_versions() -> None:
    first = CriterionDefinition(
        "permission-boundary",
        "1.0.0",
        EvaluatorKind.PERMISSION_BOUNDARY,
        "1.0.0",
        CriterionCriticality.CRITICAL,
    )
    second = replace(first, criterion_version="2.0.0")
    with pytest.raises(ValueError, match="unique"):
        p0_task_definition().rubric.__class__("rubric", "1", (first, second))


def test_contract_rejects_unsupported_evaluator_version_and_wrong_value_type() -> None:
    with pytest.raises(ValueError, match="unsupported evaluator version"):
        CriterionDefinition(
            "permission-boundary",
            "1.0.0",
            EvaluatorKind.PERMISSION_BOUNDARY,
            "2.0.0",
            CriterionCriticality.CRITICAL,
        )
    with pytest.raises(TypeError, match="outcome"):
        EvaluationInput("not-a-run-outcome", None)  # type: ignore[arg-type]


def test_p0_task_cannot_remove_or_downgrade_mandatory_criteria() -> None:
    task = p0_task_definition()
    downgraded = replace(
        task.rubric.criteria[0], criticality=CriterionCriticality.NON_CRITICAL
    )
    invalid = replace(
        task,
        rubric=replace(task.rubric, criteria=(downgraded,) + task.rubric.criteria[1:]),
    )
    with pytest.raises(ValueError, match="governed P0"):
        evaluate(
            _generated_input(CitationReference("synthetic-source", "synthetic-chunk")),
            invalid,
        )
    missing = replace(
        task, rubric=replace(task.rubric, criteria=task.rubric.criteria[:-1])
    )
    with pytest.raises(ValueError, match="governed P0"):
        evaluate(
            _generated_input(CitationReference("synthetic-source", "synthetic-chunk")),
            missing,
        )


def test_all_critical_passes_and_repeated_evaluation_is_identical() -> None:
    input_value = _generated_input(
        CitationReference("synthetic-source", "synthetic-chunk")
    )
    first = evaluate(input_value)
    assert first == evaluate(input_value)
    assert first.gate.status is GateStatus.PASS
    assert all(item.status is CriterionStatus.PASS for item in first.criteria)


@pytest.mark.parametrize(
    ("citation", "criterion_id"),
    [
        (CitationReference("outside-source", "synthetic-chunk"), "authorized-source"),
        (CitationReference("synthetic-source", "missing-chunk"), "citation-resolution"),
        (CitationReference("synthetic-source", "outside-chunk"), "citation-resolution"),
    ],
)
def test_invalid_source_or_chunk_citations_fail_closed(
    citation: CitationReference, criterion_id: str
) -> None:
    result = evaluate(_generated_input(citation))
    assert result.gate.status is GateStatus.BLOCK
    assert _criterion(result, criterion_id).status is CriterionStatus.FAIL


def test_empty_citations_are_unknown_and_block() -> None:
    input_value = _generated_input(
        CitationReference("synthetic-source", "synthetic-chunk")
    )
    assert input_value.outcome.result is not None
    empty = replace(
        input_value,
        outcome=replace(
            input_value.outcome,
            result=replace(input_value.outcome.result, citations=()),
        ),
    )
    result = evaluate(empty)
    assert result.gate.status is GateStatus.BLOCK
    assert _criterion(result, "citation-resolution").status is CriterionStatus.UNKNOWN


def test_correct_permission_stop_passes_boundary_but_blocks_output_gate() -> None:
    result = evaluate(_stopped_input())
    assert _criterion(result, "permission-boundary").status is CriterionStatus.PASS
    assert _criterion(result, "provenance-completeness").status is CriterionStatus.PASS
    assert result.gate.status is GateStatus.BLOCK


def test_missing_and_cross_run_provenance_produce_error_blocks() -> None:
    input_value = _generated_input(
        CitationReference("synthetic-source", "synthetic-chunk")
    )
    missing = evaluate(replace(input_value, provenance=None))
    assert missing.gate.status is GateStatus.BLOCK
    assert all(item.status is CriterionStatus.ERROR for item in missing.criteria)
    assert input_value.provenance is not None
    mismatched = replace(
        input_value.provenance,
        run_id=input_value.provenance.run_id.__class__("other-run"),
    )
    cross_run = evaluate(replace(input_value, provenance=mismatched))
    assert cross_run.gate.status is GateStatus.BLOCK
    assert all(item.status is CriterionStatus.ERROR for item in cross_run.criteria)
    permission_mismatch = replace(
        input_value,
        outcome=replace(
            input_value.outcome,
            permission_result=PermissionResult(PermissionState.BLOCK),
        ),
    )
    inconsistent = evaluate(permission_mismatch)
    assert inconsistent.gate.status is GateStatus.BLOCK
    assert all(item.status is CriterionStatus.ERROR for item in inconsistent.criteria)


def test_evaluator_exception_is_sanitized_error_and_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(
        _: EvaluationInput, __: evaluators.ProvenanceIndex
    ) -> tuple[CriterionStatus, EvaluationEvidence]:
        raise RuntimeError("sensitive internal diagnostic")

    registry = dict(evaluators.EVALUATOR_REGISTRY)
    registry[EvaluatorKind.AUTHORIZED_SOURCE] = broken
    monkeypatch.setattr(evaluators, "EVALUATOR_REGISTRY", MappingProxyType(registry))
    result = evaluate(
        _generated_input(CitationReference("synthetic-source", "synthetic-chunk"))
    )
    criterion = _criterion(result, "authorized-source")
    assert criterion.status is CriterionStatus.ERROR
    assert criterion.evidence.reason_codes == (ReasonCode.EVALUATOR_EXECUTION_ERROR,)
    assert "sensitive" not in repr(criterion.evidence)
    assert result.gate.status is GateStatus.BLOCK


def test_noncritical_fail_or_unknown_does_not_independently_block() -> None:
    input_value = _generated_input(
        CitationReference("synthetic-source", "synthetic-chunk")
    )
    task, definition = _task_with_optional_criterion()
    for status in (CriterionStatus.FAIL, CriterionStatus.UNKNOWN):
        results = tuple(
            _result(
                item,
                status if item == definition else CriterionStatus.PASS,
                input_value,
            )
            for item in task.rubric.criteria
        )
        assert calculate_gate(input_value, task, results).status is GateStatus.PASS


def test_execution_error_and_invalid_or_empty_result_sets_block() -> None:
    input_value = _generated_input(
        CitationReference("synthetic-source", "synthetic-chunk")
    )
    task, definition = _task_with_optional_criterion()
    passing = _passing_results(task, input_value)
    error_results = tuple(
        _result(
            item,
            CriterionStatus.ERROR if item == definition else CriterionStatus.PASS,
            input_value,
        )
        for item in task.rubric.criteria
    )
    assert calculate_gate(input_value, task, error_results).status is GateStatus.BLOCK
    assert (
        calculate_gate(input_value, p0_task_definition(), ()).status is GateStatus.BLOCK
    )
    wrong_version_results = (replace(passing[0], criterion_version="2.0.0"),) + passing[
        1:
    ]
    assert (
        calculate_gate(input_value, task, wrong_version_results).status
        is GateStatus.BLOCK
    )


def test_gate_rejects_result_with_evidence_contradicting_its_status() -> None:
    input_value = _generated_input(
        CitationReference("synthetic-source", "synthetic-chunk")
    )
    results = _passing_results(p0_task_definition(), input_value)
    contradictory = replace(
        results[0],
        evidence=EvaluationEvidence(
            (ReasonCode.EVALUATOR_EXECUTION_ERROR,),
            1,
            1,
        ),
    )
    gate = calculate_gate(
        input_value,
        p0_task_definition(),
        (contradictory,) + results[1:],
    )
    assert gate.status is GateStatus.BLOCK
    assert any(
        block.reason_code is ReasonCode.RESULT_SET_INVALID for block in gate.blocks
    )


def test_gate_rejects_fabricated_critical_pass_for_failed_input() -> None:
    input_value = _generated_input(
        CitationReference("outside-source", "synthetic-chunk")
    )
    gate = calculate_gate(
        input_value,
        p0_task_definition(),
        _passing_results(p0_task_definition(), input_value),
    )
    assert gate.status is GateStatus.BLOCK
    assert any(
        block.reason_code is ReasonCode.RESULT_SET_INVALID for block in gate.blocks
    )


def test_type_correct_inconsistent_evaluator_output_invalidates_result_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def inconsistent(
        _: EvaluationInput, __: evaluators.ProvenanceIndex
    ) -> tuple[CriterionStatus, EvaluationEvidence]:
        return CriterionStatus.PASS, EvaluationEvidence(
            (ReasonCode.EVALUATOR_EXECUTION_ERROR,), 1, 1
        )

    registry = dict(evaluators.EVALUATOR_REGISTRY)
    registry[EvaluatorKind.AUTHORIZED_SOURCE] = inconsistent
    monkeypatch.setattr(evaluators, "EVALUATOR_REGISTRY", MappingProxyType(registry))
    result = evaluate(
        _generated_input(CitationReference("synthetic-source", "synthetic-chunk"))
    )
    assert _criterion(result, "authorized-source").status is CriterionStatus.PASS
    assert result.gate.status is GateStatus.BLOCK
    assert any(
        block.reason_code is ReasonCode.RESULT_SET_INVALID
        for block in result.gate.blocks
    )


def test_completed_results_cannot_accept_a_caller_supplied_gate() -> None:
    with pytest.raises(TypeError, match="evaluation runner"):
        CriticalGateResult(GateStatus.PASS, ())
    with pytest.raises(TypeError, match="evaluation runner"):
        EvaluationResult(
            run_id=_generated_input(
                CitationReference("synthetic-source", "synthetic-chunk")
            ).outcome.run_id,
            task_id="p0-source-grounded-output",
            task_version="1.0.0",
            rubric_id="p0-deterministic-critical-gate",
            rubric_version="1.0.0",
            criteria=(),
            gate=object(),  # type: ignore[arg-type]
        )


def test_smoke_cases_match_independent_fixed_expectations() -> None:
    assert run_smoke() == (
        ("valid-generated", True),
        ("nonexistent-chunk", True),
        ("source-outside-run-context", True),
        ("permission-stopped", True),
        ("evaluator-execution-error", True),
    )
