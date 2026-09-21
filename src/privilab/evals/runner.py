"""Code-controlled evaluator execution and fail-closed critical gate."""

from __future__ import annotations

from dataclasses import dataclass

from privilab.application.provenance import RunStatus
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
    GateBlock,
    GateStatus,
    ReasonCode,
    TaskDefinition,
    _critical_gate_result,
    _evaluation_result,
    p0_task_definition,
    validate_p0_task,
)


@dataclass(frozen=True, slots=True)
class _ResultSetIssue:
    reason_code: ReasonCode


def _evidence(input_value: EvaluationInput, code: ReasonCode) -> EvaluationEvidence:
    return EvaluationEvidence(
        reason_codes=(code,),
        source_count=(
            0 if input_value.provenance is None else len(input_value.provenance.sources)
        ),
        citation_count=(
            0
            if input_value.outcome.result is None
            else len(input_value.outcome.result.citations)
        ),
    )


def _error_result(
    definition: CriterionDefinition,
    input_value: EvaluationInput,
    code: ReasonCode,
) -> CriterionResult:
    return CriterionResult(
        criterion_id=definition.criterion_id,
        criterion_version=definition.criterion_version,
        evaluator_kind=definition.evaluator_kind,
        evaluator_version=definition.evaluator_version,
        criticality=definition.criticality,
        status=CriterionStatus.ERROR,
        evidence=_evidence(input_value, code),
    )


def _run_criterion(
    definition: CriterionDefinition,
    input_value: EvaluationInput,
    index: evaluators.ProvenanceIndex,
) -> CriterionResult:
    evaluator = evaluators.EVALUATOR_REGISTRY.get(definition.evaluator_kind)
    if evaluator is None:
        return _error_result(
            definition, input_value, ReasonCode.EVALUATOR_EXECUTION_ERROR
        )
    try:
        status, evidence = evaluator(input_value, index)
        if not isinstance(status, CriterionStatus) or not isinstance(
            evidence, EvaluationEvidence
        ):
            raise TypeError("evaluator returned an invalid result")
    except Exception:
        return _error_result(
            definition, input_value, ReasonCode.EVALUATOR_EXECUTION_ERROR
        )
    return CriterionResult(
        criterion_id=definition.criterion_id,
        criterion_version=definition.criterion_version,
        evaluator_kind=definition.evaluator_kind,
        evaluator_version=definition.evaluator_version,
        criticality=definition.criticality,
        status=status,
        evidence=evidence,
    )


def _validate_result_set(
    definitions: tuple[CriterionDefinition, ...],
    results: tuple[CriterionResult, ...],
) -> _ResultSetIssue | None:
    if not definitions or not results or len(results) != len(definitions):
        return _ResultSetIssue(ReasonCode.RESULT_SET_INVALID)
    expected = {
        item.criterion_id: (
            item.criterion_version,
            item.evaluator_kind,
            item.evaluator_version,
            item.criticality,
        )
        for item in definitions
    }
    observed = {
        item.criterion_id: (
            item.criterion_version,
            item.evaluator_kind,
            item.evaluator_version,
            item.criticality,
        )
        for item in results
    }
    if expected != observed or len(observed) != len(results):
        return _ResultSetIssue(ReasonCode.RESULT_SET_INVALID)
    return None


def calculate_gate(
    input_value: EvaluationInput,
    task: TaskDefinition,
    results: tuple[CriterionResult, ...],
) -> CriticalGateResult:
    """Derive a gate from one validated P0 task and actual result values only."""
    if not isinstance(input_value, EvaluationInput):
        raise TypeError("input_value must be EvaluationInput")
    validate_p0_task(task)
    definitions = tuple(
        sorted(
            task.rubric.criteria,
            key=lambda item: (item.criterion_id, item.criterion_version),
        )
    )
    blocks: list[GateBlock] = []
    issue = _validate_result_set(definitions, results)
    if issue is not None:
        blocks.append(GateBlock(issue.reason_code))
    if input_value.outcome.status is not RunStatus.GENERATED:
        blocks.append(GateBlock(ReasonCode.OUTPUT_GATE_INELIGIBLE))
    for result in results:
        if result.status is CriterionStatus.ERROR:
            blocks.append(
                GateBlock(
                    ReasonCode.EVALUATOR_EXECUTION_ERROR,
                    result.criterion_id,
                    result.criterion_version,
                )
            )
        elif (
            result.criticality is CriterionCriticality.CRITICAL
            and result.status is not CriterionStatus.PASS
        ):
            blocks.append(
                GateBlock(
                    ReasonCode.CRITICAL_CRITERION_NOT_PASS,
                    result.criterion_id,
                    result.criterion_version,
                )
            )
    ordered_blocks = tuple(
        sorted(
            blocks,
            key=lambda item: (
                item.reason_code.value,
                item.criterion_id or "",
                item.criterion_version or "",
            ),
        )
    )
    return _critical_gate_result(
        status=GateStatus.BLOCK if ordered_blocks else GateStatus.PASS,
        blocks=ordered_blocks,
    )


def evaluate(
    input_value: EvaluationInput,
    task: TaskDefinition | None = None,
) -> EvaluationResult:
    """Evaluate every P0 criterion deterministically and fail closed on faults.

    This validates consistency of typed objects only. It does not cryptographically
    attest their origin; production callers must supply provenance from the
    approved application/store path.
    """
    if not isinstance(input_value, EvaluationInput):
        raise TypeError("input_value must be EvaluationInput")
    active_task = p0_task_definition() if task is None else task
    validate_p0_task(active_task)
    definitions = tuple(
        sorted(
            active_task.rubric.criteria,
            key=lambda item: (item.criterion_id, item.criterion_version),
        )
    )
    input_issue = evaluators.input_consistency_issue(input_value)
    if input_issue is not None:
        results = tuple(
            _error_result(definition, input_value, input_issue)
            for definition in definitions
        )
    else:
        try:
            assert input_value.provenance is not None
            index = evaluators.provenance_index(input_value.provenance)
        except Exception:
            results = tuple(
                _error_result(definition, input_value, ReasonCode.INPUT_MALFORMED)
                for definition in definitions
            )
        else:
            results = tuple(
                _run_criterion(definition, input_value, index)
                for definition in definitions
            )
    return _evaluation_result(
        run_id=input_value.outcome.run_id,
        task_id=active_task.task_id,
        task_version=active_task.task_version,
        rubric_id=active_task.rubric.rubric_id,
        rubric_version=active_task.rubric.rubric_version,
        criteria=results,
        gate=calculate_gate(input_value, active_task, results),
    )


__all__ = ["calculate_gate", "evaluate"]
