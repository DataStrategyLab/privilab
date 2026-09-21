"""Immutable, metadata-only contracts for deterministic P0 evaluation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Self, cast

from privilab.application.provenance import RunId, RunProvenance
from privilab.application.run_service import RunOutcome


def _identifier(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty, trimmed string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field_name} must be UTF-8 encodable") from error


def _exact_fields(value: dict[str, object], fields: set[str], name: str) -> None:
    if set(value) != fields:
        raise ValueError(f"{name} fields do not match the contract")


def _json_object_without_duplicates(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate evaluation field {key!r}")
        value[key] = item
    return value


class CriterionCriticality(StrEnum):
    CRITICAL = "CRITICAL"
    NON_CRITICAL = "NON_CRITICAL"


class CriterionStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class EvaluatorKind(StrEnum):
    PERMISSION_BOUNDARY = "permission-boundary"
    AUTHORIZED_SOURCE = "authorized-source"
    CITATION_RESOLUTION = "citation-resolution"
    PROVENANCE_COMPLETENESS = "provenance-completeness"


class GateStatus(StrEnum):
    PASS = "PASS"
    BLOCK = "BLOCK"


class ReasonCode(StrEnum):
    INPUT_MISSING_PROVENANCE = "INPUT_MISSING_PROVENANCE"
    INPUT_INCONSISTENT = "INPUT_INCONSISTENT"
    INPUT_MALFORMED = "INPUT_MALFORMED"
    PERMISSION_BOUNDARY_RESPECTED = "PERMISSION_BOUNDARY_RESPECTED"
    PERMISSION_BOUNDARY_VIOLATION = "PERMISSION_BOUNDARY_VIOLATION"
    GENERATED_OUTPUT_UNAVAILABLE = "GENERATED_OUTPUT_UNAVAILABLE"
    SOURCES_IN_RUN_CONTEXT = "SOURCES_IN_RUN_CONTEXT"
    SOURCE_NOT_IN_RUN_CONTEXT = "SOURCE_NOT_IN_RUN_CONTEXT"
    CITATIONS_RESOLVED = "CITATIONS_RESOLVED"
    CITATION_NOT_IN_RUN_CONTEXT = "CITATION_NOT_IN_RUN_CONTEXT"
    CITATION_REQUIRED = "CITATION_REQUIRED"
    PROVENANCE_COMPLETE = "PROVENANCE_COMPLETE"
    PROVENANCE_INCOMPLETE = "PROVENANCE_INCOMPLETE"
    EVALUATOR_EXECUTION_ERROR = "EVALUATOR_EXECUTION_ERROR"
    EVALUATOR_RESULT_MALFORMED = "EVALUATOR_RESULT_MALFORMED"
    RESULT_SET_INVALID = "RESULT_SET_INVALID"
    OUTPUT_GATE_INELIGIBLE = "OUTPUT_GATE_INELIGIBLE"
    CRITICAL_CRITERION_NOT_PASS = "CRITICAL_CRITERION_NOT_PASS"


_SUPPORTED_EVALUATOR_VERSION = "1.0.0"
_EVALUATION_RESULT_AUTHORITY = object()
_P0_CRITERIA = (
    ("authorized-source", EvaluatorKind.AUTHORIZED_SOURCE),
    ("citation-resolution", EvaluatorKind.CITATION_RESOLUTION),
    ("permission-boundary", EvaluatorKind.PERMISSION_BOUNDARY),
    ("provenance-completeness", EvaluatorKind.PROVENANCE_COMPLETENESS),
)


@dataclass(frozen=True, slots=True)
class CriterionDefinition:
    """One code-controlled deterministic check in a governed rubric."""

    criterion_id: str
    criterion_version: str
    evaluator_kind: EvaluatorKind
    evaluator_version: str
    criticality: CriterionCriticality

    def __post_init__(self) -> None:
        _identifier(self.criterion_id, "criterion_id")
        _identifier(self.criterion_version, "criterion_version")
        if not isinstance(self.evaluator_kind, EvaluatorKind):
            raise TypeError("evaluator_kind must be EvaluatorKind")
        _identifier(self.evaluator_version, "evaluator_version")
        if self.evaluator_version != _SUPPORTED_EVALUATOR_VERSION:
            raise ValueError("unsupported evaluator version")
        if not isinstance(self.criticality, CriterionCriticality):
            raise TypeError("criticality must be CriterionCriticality")

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if not isinstance(value, dict):
            raise ValueError("criterion definition must be an object")
        raw = cast(dict[str, object], value)
        _exact_fields(
            raw,
            {
                "criterion_id",
                "criterion_version",
                "evaluator_kind",
                "evaluator_version",
                "criticality",
            },
            "criterion definition",
        )
        raw_evaluator_kind = raw["evaluator_kind"]
        raw_criticality = raw["criticality"]
        if not isinstance(raw_evaluator_kind, str) or not isinstance(
            raw_criticality, str
        ):
            raise ValueError("criterion definition enum values must be strings")
        try:
            evaluator_kind = EvaluatorKind(raw_evaluator_kind)
            criticality = CriterionCriticality(raw_criticality)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "criterion definition has an unsupported enum value"
            ) from error
        return cls(
            criterion_id=cast(str, raw["criterion_id"]),
            criterion_version=cast(str, raw["criterion_version"]),
            evaluator_kind=evaluator_kind,
            evaluator_version=cast(str, raw["evaluator_version"]),
            criticality=criticality,
        )


@dataclass(frozen=True, slots=True)
class EvaluationRubric:
    rubric_id: str
    rubric_version: str
    criteria: tuple[CriterionDefinition, ...]

    def __post_init__(self) -> None:
        _identifier(self.rubric_id, "rubric_id")
        _identifier(self.rubric_version, "rubric_version")
        if not isinstance(self.criteria, tuple) or not self.criteria:
            raise ValueError("criteria must be a non-empty tuple")
        if any(not isinstance(item, CriterionDefinition) for item in self.criteria):
            raise TypeError("criteria must contain CriterionDefinition values")
        criterion_ids = [item.criterion_id for item in self.criteria]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("criterion IDs must be unique")

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if not isinstance(value, dict):
            raise ValueError("rubric must be an object")
        raw = cast(dict[str, object], value)
        _exact_fields(raw, {"rubric_id", "rubric_version", "criteria"}, "rubric")
        raw_criteria = raw["criteria"]
        if not isinstance(raw_criteria, list):
            raise ValueError("rubric criteria must be an array")
        return cls(
            rubric_id=cast(str, raw["rubric_id"]),
            rubric_version=cast(str, raw["rubric_version"]),
            criteria=tuple(
                CriterionDefinition.from_dict(item) for item in raw_criteria
            ),
        )


@dataclass(frozen=True, slots=True)
class TaskDefinition:
    """An immutable task/rubric definition; it contains no executable code."""

    task_id: str
    task_version: str
    rubric: EvaluationRubric

    def __post_init__(self) -> None:
        _identifier(self.task_id, "task_id")
        _identifier(self.task_version, "task_version")
        if not isinstance(self.rubric, EvaluationRubric):
            raise TypeError("rubric must be EvaluationRubric")

    @classmethod
    def from_json(cls, payload: str) -> Self:
        if not isinstance(payload, str):
            raise TypeError("task definition payload must be a string")
        try:
            decoded = json.loads(
                payload, object_pairs_hook=_json_object_without_duplicates
            )
        except (json.JSONDecodeError, RecursionError, TypeError, ValueError) as error:
            raise ValueError("task definition must be valid JSON") from error
        if not isinstance(decoded, dict):
            raise ValueError("task definition JSON must be an object")
        raw = cast(dict[str, object], decoded)
        _exact_fields(raw, {"task_id", "task_version", "rubric"}, "task definition")
        return cls(
            task_id=cast(str, raw["task_id"]),
            task_version=cast(str, raw["task_version"]),
            rubric=EvaluationRubric.from_dict(raw["rubric"]),
        )


@dataclass(frozen=True, slots=True)
class EvaluationInput:
    """Trusted DSL-111 state, projected without copying any source content."""

    outcome: RunOutcome
    provenance: RunProvenance | None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, RunOutcome):
            raise TypeError("outcome must be RunOutcome")
        if self.provenance is not None and not isinstance(
            self.provenance, RunProvenance
        ):
            raise TypeError("provenance must be RunProvenance or None")


@dataclass(frozen=True, slots=True)
class EvaluationEvidence:
    """Bounded metadata-only evidence; it never includes source or answer text."""

    reason_codes: tuple[ReasonCode, ...]
    source_count: int
    citation_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.reason_codes, tuple) or any(
            not isinstance(code, ReasonCode) for code in self.reason_codes
        ):
            raise TypeError("reason_codes must be a tuple of ReasonCode values")
        if (
            len(self.reason_codes) > 8
            or tuple(sorted(set(self.reason_codes), key=lambda item: item.value))
            != self.reason_codes
        ):
            raise ValueError("reason_codes must be unique, sorted, and bounded")
        for count, field_name in (
            (self.source_count, "source_count"),
            (self.citation_count, "citation_count"),
        ):
            if type(count) is not int or count < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class CriterionResult:
    criterion_id: str
    criterion_version: str
    evaluator_kind: EvaluatorKind
    evaluator_version: str
    criticality: CriterionCriticality
    status: CriterionStatus
    evidence: EvaluationEvidence

    def __post_init__(self) -> None:
        _identifier(self.criterion_id, "criterion_id")
        _identifier(self.criterion_version, "criterion_version")
        if not isinstance(self.evaluator_kind, EvaluatorKind):
            raise TypeError("evaluator_kind must be EvaluatorKind")
        _identifier(self.evaluator_version, "evaluator_version")
        if not isinstance(self.criticality, CriterionCriticality):
            raise TypeError("criticality must be CriterionCriticality")
        if not isinstance(self.status, CriterionStatus):
            raise TypeError("status must be CriterionStatus")
        if not isinstance(self.evidence, EvaluationEvidence):
            raise TypeError("evidence must be EvaluationEvidence")


@dataclass(frozen=True, slots=True)
class GateBlock:
    reason_code: ReasonCode
    criterion_id: str | None = None
    criterion_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reason_code, ReasonCode):
            raise TypeError("reason_code must be ReasonCode")
        if (self.criterion_id is None) != (self.criterion_version is None):
            raise ValueError("criterion ID and version must be present together")
        if self.criterion_id is not None:
            _identifier(self.criterion_id, "blocking criterion ID")
            _identifier(self.criterion_version, "blocking criterion version")


@dataclass(frozen=True, slots=True, init=False)
class CriticalGateResult:
    status: GateStatus
    blocks: tuple[GateBlock, ...]

    def __init__(
        self,
        status: GateStatus,
        blocks: tuple[GateBlock, ...],
        *,
        _authorized: object | None = None,
    ) -> None:
        if _authorized is not _EVALUATION_RESULT_AUTHORITY:
            raise TypeError(
                "CriticalGateResult must be created by the evaluation runner"
            )
        if not isinstance(status, GateStatus):
            raise TypeError("status must be GateStatus")
        if not isinstance(blocks, tuple) or any(
            not isinstance(block, GateBlock) for block in blocks
        ):
            raise TypeError("blocks must be a tuple of GateBlock values")
        if (status is GateStatus.PASS) != (not blocks):
            raise ValueError("gate status must match blocks")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "blocks", blocks)


@dataclass(frozen=True, slots=True, init=False)
class EvaluationResult:
    run_id: RunId
    task_id: str
    task_version: str
    rubric_id: str
    rubric_version: str
    criteria: tuple[CriterionResult, ...]
    gate: CriticalGateResult

    def __init__(
        self,
        *,
        run_id: RunId,
        task_id: str,
        task_version: str,
        rubric_id: str,
        rubric_version: str,
        criteria: tuple[CriterionResult, ...],
        gate: CriticalGateResult,
        _authorized: object | None = None,
    ) -> None:
        if _authorized is not _EVALUATION_RESULT_AUTHORITY:
            raise TypeError("EvaluationResult must be created by the evaluation runner")
        if not isinstance(run_id, RunId):
            raise TypeError("run_id must be RunId")
        for field_name, value in (
            ("task_id", task_id),
            ("task_version", task_version),
            ("rubric_id", rubric_id),
            ("rubric_version", rubric_version),
        ):
            _identifier(value, field_name)
        if not isinstance(criteria, tuple) or not criteria:
            raise ValueError("criteria must be a non-empty tuple")
        if any(not isinstance(item, CriterionResult) for item in criteria):
            raise TypeError("criteria must contain CriterionResult values")
        identities = [(item.criterion_id, item.criterion_version) for item in criteria]
        if len(identities) != len(set(identities)):
            raise ValueError("criterion results must be unique")
        if not isinstance(gate, CriticalGateResult):
            raise TypeError("gate must be CriticalGateResult")
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "task_version", task_version)
        object.__setattr__(self, "rubric_id", rubric_id)
        object.__setattr__(self, "rubric_version", rubric_version)
        object.__setattr__(self, "criteria", criteria)
        object.__setattr__(self, "gate", gate)


def p0_task_definition() -> TaskDefinition:
    """Return the fixed P0 task; callers cannot remove or downgrade its checks."""
    return TaskDefinition(
        task_id="p0-source-grounded-output",
        task_version="1.0.0",
        rubric=EvaluationRubric(
            rubric_id="p0-deterministic-critical-gate",
            rubric_version="1.0.0",
            criteria=tuple(
                CriterionDefinition(
                    criterion_id=criterion_id,
                    criterion_version="1.0.0",
                    evaluator_kind=evaluator_kind,
                    evaluator_version=_SUPPORTED_EVALUATOR_VERSION,
                    criticality=CriterionCriticality.CRITICAL,
                )
                for criterion_id, evaluator_kind in _P0_CRITERIA
            ),
        ),
    )


def validate_p0_task(task: TaskDefinition) -> None:
    """Reject task definitions that weaken or alter the approved P0 gate."""
    if not isinstance(task, TaskDefinition):
        raise TypeError("task must be TaskDefinition")
    expected = p0_task_definition()
    if (
        task.task_id != expected.task_id
        or task.task_version != expected.task_version
        or task.rubric.rubric_id != expected.rubric.rubric_id
        or task.rubric.rubric_version != expected.rubric.rubric_version
    ):
        raise ValueError("task definition does not match the governed P0 evaluation")
    expected_criteria = {item.criterion_id: item for item in expected.rubric.criteria}
    actual_criteria = {item.criterion_id: item for item in task.rubric.criteria}
    if any(
        actual_criteria.get(criterion_id) != expected_criterion
        for criterion_id, expected_criterion in expected_criteria.items()
    ):
        raise ValueError("task definition does not match the governed P0 evaluation")
    if any(
        criterion_id not in expected_criteria
        and criterion.criticality is not CriterionCriticality.NON_CRITICAL
        for criterion_id, criterion in actual_criteria.items()
    ):
        raise ValueError("additional P0 criteria must be non-critical")


def _critical_gate_result(
    status: GateStatus,
    blocks: tuple[GateBlock, ...],
) -> CriticalGateResult:
    return CriticalGateResult(
        status,
        blocks,
        _authorized=_EVALUATION_RESULT_AUTHORITY,
    )


def _evaluation_result(
    *,
    run_id: RunId,
    task_id: str,
    task_version: str,
    rubric_id: str,
    rubric_version: str,
    criteria: tuple[CriterionResult, ...],
    gate: CriticalGateResult,
) -> EvaluationResult:
    return EvaluationResult(
        run_id=run_id,
        task_id=task_id,
        task_version=task_version,
        rubric_id=rubric_id,
        rubric_version=rubric_version,
        criteria=criteria,
        gate=gate,
        _authorized=_EVALUATION_RESULT_AUTHORITY,
    )


__all__ = [
    "CriterionCriticality",
    "CriterionDefinition",
    "CriterionResult",
    "CriterionStatus",
    "CriticalGateResult",
    "EvaluationEvidence",
    "EvaluationInput",
    "EvaluationResult",
    "EvaluationRubric",
    "EvaluatorKind",
    "GateBlock",
    "GateStatus",
    "ReasonCode",
    "TaskDefinition",
    "p0_task_definition",
    "validate_p0_task",
]
