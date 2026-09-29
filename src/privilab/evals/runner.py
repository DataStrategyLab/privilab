"""Code-controlled evaluator execution and fail-closed critical gate."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

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
    EvaluatorKind,
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


_STATUS_EVIDENCE_CODES: dict[
    EvaluatorKind, dict[CriterionStatus, frozenset[ReasonCode]]
] = {
    EvaluatorKind.PERMISSION_BOUNDARY: {
        CriterionStatus.PASS: frozenset({ReasonCode.PERMISSION_BOUNDARY_RESPECTED}),
        CriterionStatus.FAIL: frozenset({ReasonCode.PERMISSION_BOUNDARY_VIOLATION}),
    },
    EvaluatorKind.AUTHORIZED_SOURCE: {
        CriterionStatus.PASS: frozenset({ReasonCode.SOURCES_IN_RUN_CONTEXT}),
        CriterionStatus.FAIL: frozenset({ReasonCode.SOURCE_NOT_IN_RUN_CONTEXT}),
        CriterionStatus.UNKNOWN: frozenset(
            {
                ReasonCode.GENERATED_OUTPUT_UNAVAILABLE,
                ReasonCode.CITATION_REQUIRED,
            }
        ),
    },
    EvaluatorKind.CITATION_RESOLUTION: {
        CriterionStatus.PASS: frozenset({ReasonCode.CITATIONS_RESOLVED}),
        CriterionStatus.FAIL: frozenset({ReasonCode.CITATION_NOT_IN_RUN_CONTEXT}),
        CriterionStatus.UNKNOWN: frozenset(
            {
                ReasonCode.GENERATED_OUTPUT_UNAVAILABLE,
                ReasonCode.CITATION_REQUIRED,
            }
        ),
    },
    EvaluatorKind.PROVENANCE_COMPLETENESS: {
        CriterionStatus.PASS: frozenset({ReasonCode.PROVENANCE_COMPLETE}),
        CriterionStatus.FAIL: frozenset({ReasonCode.PROVENANCE_INCOMPLETE}),
    },
}
_ERROR_EVIDENCE_CODES = frozenset(
    {
        ReasonCode.INPUT_MISSING_PROVENANCE,
        ReasonCode.INPUT_INCONSISTENT,
        ReasonCode.INPUT_MALFORMED,
        ReasonCode.EVALUATOR_EXECUTION_ERROR,
        ReasonCode.EVALUATOR_RESULT_MALFORMED,
    }
)
_CRITICAL_CONTRACT_EVALUATORS = MappingProxyType(
    {
        EvaluatorKind.PERMISSION_BOUNDARY: evaluators.permission_boundary,
        EvaluatorKind.AUTHORIZED_SOURCE: evaluators.authorized_source,
        EvaluatorKind.CITATION_RESOLUTION: evaluators.citation_resolution,
        EvaluatorKind.PROVENANCE_COMPLETENESS: evaluators.provenance_completeness,
    }
)


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
    input_value: EvaluationInput,
) -> _ResultSetIssue | None:
    if (
        not definitions
        or not isinstance(results, tuple)
        or not results
        or len(results) != len(definitions)
        or any(not isinstance(result, CriterionResult) for result in results)
    ):
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
    definitions_by_id = {
        definition.criterion_id: definition for definition in definitions
    }
    if any(
        not _matches_evidence_contract(
            input_value, definitions_by_id[result.criterion_id], result
        )
        for result in results
    ):
        return _ResultSetIssue(ReasonCode.RESULT_SET_INVALID)
    return None


def _matches_evidence_contract(
    input_value: EvaluationInput,
    definition: CriterionDefinition,
    result: CriterionResult,
) -> bool:
    """Accept only bounded evidence that can justify the reported status."""
    evidence = result.evidence
    expected_source_count = (
        0 if input_value.provenance is None else len(input_value.provenance.sources)
    )
    expected_citation_count = (
        0
        if input_value.outcome.result is None
        else len(input_value.outcome.result.citations)
    )
    if (
        evidence.source_count != expected_source_count
        or evidence.citation_count != expected_citation_count
        or len(evidence.reason_codes) != 1
    ):
        return False
    reason_code = evidence.reason_codes[0]
    if result.status is CriterionStatus.ERROR:
        return reason_code in _ERROR_EVIDENCE_CODES
    if reason_code not in _STATUS_EVIDENCE_CODES[result.evaluator_kind].get(
        result.status, frozenset()
    ):
        return False
    if definition.criticality is not CriterionCriticality.CRITICAL:
        return True
    if evaluators.input_consistency_issue(input_value) is not None:
        return False
    try:
        if input_value.provenance is None:
            return False
        expected_status, expected_evidence = _CRITICAL_CONTRACT_EVALUATORS[
            definition.evaluator_kind
        ](input_value, evaluators.provenance_index(input_value.provenance))
    except Exception:
        return False
    return result.status is expected_status and evidence == expected_evidence


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
    issue = _validate_result_set(definitions, results, input_value)
    if issue is not None:
        blocks.append(GateBlock(issue.reason_code))
    if input_value.outcome.status is not RunStatus.GENERATED:
        blocks.append(GateBlock(ReasonCode.OUTPUT_GATE_INELIGIBLE))
    if issue is None:
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
