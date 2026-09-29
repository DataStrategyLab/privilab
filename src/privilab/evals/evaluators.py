"""Pure deterministic criteria over trusted DSL-111 run metadata only."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from privilab.application.provenance import (
    ChunkProvenance,
    ContextProvenance,
    FailureStage,
    PermissionProvenance,
    PermissionStopReason,
    RunConfiguration,
    RunProvenance,
    RunStatus,
    SourceProvenance,
)
from privilab.domain import PermissionState
from privilab.evals.contracts import (
    CriterionStatus,
    EvaluationEvidence,
    EvaluationInput,
    EvaluatorKind,
    ReasonCode,
)


@dataclass(frozen=True, slots=True)
class ProvenanceIndex:
    """One immutable source/chunk index shared by source-based criteria."""

    source_ids: frozenset[str]
    source_chunk_pairs: frozenset[tuple[str, str]]


Evaluator = Callable[
    [EvaluationInput, ProvenanceIndex], tuple[CriterionStatus, EvaluationEvidence]
]


def provenance_index(provenance: RunProvenance) -> ProvenanceIndex:
    """Project trusted run provenance to identifiers only, without source text."""
    return ProvenanceIndex(
        source_ids=frozenset(source.source_id for source in provenance.sources),
        source_chunk_pairs=frozenset(
            (source.source_id, chunk.chunk_id)
            for source in provenance.sources
            for chunk in source.chunks
        ),
    )


def _evidence(input_value: EvaluationInput, *codes: ReasonCode) -> EvaluationEvidence:
    result = input_value.outcome.result
    return EvaluationEvidence(
        reason_codes=tuple(sorted(set(codes), key=lambda code: code.value)),
        source_count=(
            0 if input_value.provenance is None else len(input_value.provenance.sources)
        ),
        citation_count=0 if result is None else len(result.citations),
    )


def input_consistency_issue(input_value: EvaluationInput) -> ReasonCode | None:
    """Validate cross-object state without treating matching IDs as sufficient."""
    provenance = input_value.provenance
    if provenance is None:
        return ReasonCode.INPUT_MISSING_PROVENANCE
    outcome = input_value.outcome
    try:
        if (
            outcome.run_id != provenance.run_id
            or outcome.status is not provenance.status
            or outcome.failure_stage is not provenance.failure_stage
        ):
            return ReasonCode.INPUT_INCONSISTENT
        outcome_permission = outcome.permission_result
        provenance_permission = provenance.permission
        if (outcome_permission is None) != (provenance_permission is None):
            return ReasonCode.INPUT_INCONSISTENT
        if outcome_permission is not None and provenance_permission is not None:
            if outcome_permission.state is not provenance_permission.state:
                return ReasonCode.INPUT_INCONSISTENT
            outcome_conditions = frozenset(
                condition.value for condition in outcome_permission.condition_ids
            )
            if outcome_conditions != frozenset(
                provenance_permission.unresolved_condition_ids
            ):
                return ReasonCode.INPUT_INCONSISTENT
    except (AttributeError, TypeError, ValueError):
        return ReasonCode.INPUT_MALFORMED
    return None


def _failed_run_respected(provenance: RunProvenance) -> bool:
    permission = provenance.permission
    if provenance.failure_stage is None:
        return False
    expected = {
        FailureStage.PERMISSION: (None, False, False),
        FailureStage.AUTHORIZATION: (PermissionState.ALLOW, False, False),
        FailureStage.RETRIEVAL: (PermissionState.ALLOW, True, False),
        FailureStage.MODEL: (PermissionState.ALLOW, True, True),
    }.get(provenance.failure_stage)
    if expected is None:
        return False
    permission_state, retrieval_called, model_called = expected
    return (
        (None if permission is None else permission.state) is permission_state
        and provenance.retrieval_called is retrieval_called
        and provenance.model_called is model_called
        and provenance.stop_reason is None
    )


def permission_boundary(
    input_value: EvaluationInput,
    _: ProvenanceIndex,
) -> tuple[CriterionStatus, EvaluationEvidence]:
    """Check recorded state progression without re-evaluating permission policy."""
    provenance = input_value.provenance
    if provenance is None:
        return CriterionStatus.ERROR, _evidence(
            input_value, ReasonCode.INPUT_MISSING_PROVENANCE
        )
    permission = provenance.permission
    try:
        if provenance.status is RunStatus.GENERATED:
            respected = (
                input_value.outcome.result is not None
                and permission is not None
                and permission.state is PermissionState.ALLOW
                and provenance.retrieval_called
                and provenance.model_called
                and provenance.stop_reason is None
                and provenance.failure_stage is None
            )
        elif provenance.status is RunStatus.PERMISSION_STOPPED:
            respected = (
                input_value.outcome.result is None
                and permission is not None
                and not provenance.retrieval_called
                and not provenance.model_called
                and not provenance.sources
                and provenance.failure_stage is None
                and provenance.stop_reason
                is {
                    PermissionState.BLOCK: PermissionStopReason.BLOCK,
                    PermissionState.UNKNOWN: PermissionStopReason.UNKNOWN,
                    PermissionState.CONDITIONAL: (
                        PermissionStopReason.UNRESOLVED_CONDITIONS
                    ),
                }.get(permission.state)
            )
        elif provenance.status is RunStatus.FAILED:
            respected = input_value.outcome.result is None and _failed_run_respected(
                provenance
            )
        else:
            respected = False
    except (AttributeError, TypeError, ValueError):
        return CriterionStatus.ERROR, _evidence(input_value, ReasonCode.INPUT_MALFORMED)
    if respected:
        return CriterionStatus.PASS, _evidence(
            input_value, ReasonCode.PERMISSION_BOUNDARY_RESPECTED
        )
    return CriterionStatus.FAIL, _evidence(
        input_value, ReasonCode.PERMISSION_BOUNDARY_VIOLATION
    )


def authorized_source(
    input_value: EvaluationInput,
    index: ProvenanceIndex,
) -> tuple[CriterionStatus, EvaluationEvidence]:
    """Verify cited source IDs stayed inside this run's trusted source set."""
    result = input_value.outcome.result
    if result is None:
        return CriterionStatus.UNKNOWN, _evidence(
            input_value, ReasonCode.GENERATED_OUTPUT_UNAVAILABLE
        )
    if not result.citations:
        return CriterionStatus.UNKNOWN, _evidence(
            input_value, ReasonCode.CITATION_REQUIRED
        )
    if any(citation.source_id not in index.source_ids for citation in result.citations):
        return CriterionStatus.FAIL, _evidence(
            input_value, ReasonCode.SOURCE_NOT_IN_RUN_CONTEXT
        )
    return CriterionStatus.PASS, _evidence(
        input_value, ReasonCode.SOURCES_IN_RUN_CONTEXT
    )


def citation_resolution(
    input_value: EvaluationInput,
    index: ProvenanceIndex,
) -> tuple[CriterionStatus, EvaluationEvidence]:
    """Resolve each model citation against an exact source/chunk pair in this run."""
    result = input_value.outcome.result
    if result is None:
        return CriterionStatus.UNKNOWN, _evidence(
            input_value, ReasonCode.GENERATED_OUTPUT_UNAVAILABLE
        )
    if not result.citations:
        return CriterionStatus.UNKNOWN, _evidence(
            input_value, ReasonCode.CITATION_REQUIRED
        )
    if any(
        (citation.source_id, citation.chunk_id) not in index.source_chunk_pairs
        for citation in result.citations
    ):
        return CriterionStatus.FAIL, _evidence(
            input_value, ReasonCode.CITATION_NOT_IN_RUN_CONTEXT
        )
    return CriterionStatus.PASS, _evidence(input_value, ReasonCode.CITATIONS_RESOLVED)


def _complete_provenance(provenance: RunProvenance) -> bool:
    """Check exposed P0 metadata; validation does not attest persisted provenance."""
    if not (
        isinstance(provenance.run_id.value, str)
        and isinstance(provenance.started_at, datetime)
        and isinstance(provenance.completed_at, datetime)
        and isinstance(provenance.context, ContextProvenance)
        and isinstance(provenance.configuration, RunConfiguration)
        and isinstance(provenance.configuration_hash, str)
        and provenance.configuration_hash.startswith("sha256:")
        and isinstance(provenance.retrieval_called, bool)
        and isinstance(provenance.model_called, bool)
        and isinstance(provenance.sources, tuple)
        and all(isinstance(source, SourceProvenance) for source in provenance.sources)
    ):
        return False
    if any(
        not isinstance(chunk, ChunkProvenance)
        for source in provenance.sources
        for chunk in source.chunks
    ):
        return False
    if provenance.status is RunStatus.GENERATED:
        return (
            isinstance(provenance.permission, PermissionProvenance)
            and provenance.permission.state is PermissionState.ALLOW
            and provenance.retrieval_called
            and provenance.model_called
            and provenance.stop_reason is None
            and provenance.failure_stage is None
        )
    if provenance.status is RunStatus.PERMISSION_STOPPED:
        if not isinstance(provenance.permission, PermissionProvenance):
            return False
        expected_stop_reason = {
            PermissionState.BLOCK: PermissionStopReason.BLOCK,
            PermissionState.UNKNOWN: PermissionStopReason.UNKNOWN,
            PermissionState.CONDITIONAL: PermissionStopReason.UNRESOLVED_CONDITIONS,
        }.get(provenance.permission.state)
        return (
            not provenance.retrieval_called
            and not provenance.model_called
            and not provenance.sources
            and provenance.stop_reason is expected_stop_reason
            and provenance.failure_stage is None
        )
    if provenance.status is RunStatus.FAILED:
        return _failed_run_respected(provenance)
    return False


def provenance_completeness(
    input_value: EvaluationInput,
    _: ProvenanceIndex,
) -> tuple[CriterionStatus, EvaluationEvidence]:
    """Check only existing reconstruction metadata appropriate to terminal state."""
    provenance = input_value.provenance
    if provenance is None:
        return CriterionStatus.ERROR, _evidence(
            input_value, ReasonCode.INPUT_MISSING_PROVENANCE
        )
    try:
        complete = _complete_provenance(provenance)
    except (AttributeError, TypeError, ValueError):
        return CriterionStatus.ERROR, _evidence(input_value, ReasonCode.INPUT_MALFORMED)
    if complete:
        return CriterionStatus.PASS, _evidence(
            input_value, ReasonCode.PROVENANCE_COMPLETE
        )
    return CriterionStatus.FAIL, _evidence(
        input_value, ReasonCode.PROVENANCE_INCOMPLETE
    )


EVALUATOR_REGISTRY: MappingProxyType[EvaluatorKind, Evaluator] = MappingProxyType(
    {
        EvaluatorKind.PERMISSION_BOUNDARY: permission_boundary,
        EvaluatorKind.AUTHORIZED_SOURCE: authorized_source,
        EvaluatorKind.CITATION_RESOLUTION: citation_resolution,
        EvaluatorKind.PROVENANCE_COMPLETENESS: provenance_completeness,
    }
)


__all__ = [
    "EVALUATOR_REGISTRY",
    "Evaluator",
    "ProvenanceIndex",
    "input_consistency_issue",
    "provenance_index",
]
