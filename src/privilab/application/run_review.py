"""Metadata evidence and separate human decisions for the local fixture preview."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from privilab.application.provenance import (
    ProvenanceStore,
    RunId,
    RunProvenance,
    RunStatus,
)
from privilab.application.run_service import RunOutcome, RunService
from privilab.domain import SyntheticRequestContext
from privilab.evals import (
    CriterionResult,
    CriterionStatus,
    EvaluationInput,
    EvaluationResult,
    GateBlock,
    GateStatus,
    ReasonCode,
    evaluate,
    p0_task_definition,
)

SYNTHETIC_REVIEWER = "synthetic-local-reviewer"

# Version 1 serialization vocabulary, not executable evaluator/gate policy.
_CRITERION_CODES = {
    "permission-boundary": {
        CriterionStatus.PASS: {ReasonCode.PERMISSION_BOUNDARY_RESPECTED},
        CriterionStatus.FAIL: {ReasonCode.PERMISSION_BOUNDARY_VIOLATION},
    },
    "authorized-source": {
        CriterionStatus.PASS: {ReasonCode.SOURCES_IN_RUN_CONTEXT},
        CriterionStatus.FAIL: {ReasonCode.SOURCE_NOT_IN_RUN_CONTEXT},
        CriterionStatus.UNKNOWN: {
            ReasonCode.GENERATED_OUTPUT_UNAVAILABLE,
            ReasonCode.CITATION_REQUIRED,
        },
    },
    "citation-resolution": {
        CriterionStatus.PASS: {ReasonCode.CITATIONS_RESOLVED},
        CriterionStatus.FAIL: {ReasonCode.CITATION_NOT_IN_RUN_CONTEXT},
        CriterionStatus.UNKNOWN: {
            ReasonCode.GENERATED_OUTPUT_UNAVAILABLE,
            ReasonCode.CITATION_REQUIRED,
        },
    },
    "provenance-completeness": {
        CriterionStatus.PASS: {ReasonCode.PROVENANCE_COMPLETE},
        CriterionStatus.FAIL: {ReasonCode.PROVENANCE_INCOMPLETE},
    },
}
_ERROR_CODES = {
    ReasonCode.INPUT_MISSING_PROVENANCE,
    ReasonCode.INPUT_INCONSISTENT,
    ReasonCode.INPUT_MALFORMED,
    ReasonCode.EVALUATOR_EXECUTION_ERROR,
    ReasonCode.EVALUATOR_RESULT_MALFORMED,
}


def _timestamp(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("evidence timestamp must be timezone-aware")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError):
        raise ValueError(
            "evidence timestamp is outside the supported UTC range"
        ) from None


@dataclass(frozen=True, slots=True)
class EvaluationSnapshot:
    """Recorded evaluation metadata, never a replacement evaluation authority."""

    run_id: RunId
    schema_version: str
    evaluated_at: datetime
    task_id: str
    task_version: str
    rubric_id: str
    rubric_version: str
    criteria: tuple[CriterionResult, ...]
    gate_status: GateStatus
    blocks: tuple[GateBlock, ...]

    def __post_init__(self) -> None:
        task = p0_task_definition()
        if not isinstance(self.run_id, RunId) or self.schema_version != "1":
            raise ValueError("unsupported evaluation snapshot")
        object.__setattr__(self, "evaluated_at", _timestamp(self.evaluated_at))
        if (self.task_id, self.task_version, self.rubric_id, self.rubric_version) != (
            task.task_id,
            task.task_version,
            task.rubric.rubric_id,
            task.rubric.rubric_version,
        ):
            raise ValueError("unsupported evaluation definition")
        expected = {item.criterion_id: item for item in task.rubric.criteria}
        if not isinstance(self.criteria, tuple) or len(self.criteria) != len(expected):
            raise ValueError("incomplete evaluation snapshot")
        seen: set[str] = set()
        for item in self.criteria:
            if not isinstance(item, CriterionResult) or item.criterion_id in seen:
                raise ValueError("invalid evaluation criteria")
            seen.add(item.criterion_id)
            definition = expected.get(item.criterion_id)
            if definition is None or (
                item.criterion_version,
                item.evaluator_kind,
                item.evaluator_version,
                item.criticality,
            ) != (
                definition.criterion_version,
                definition.evaluator_kind,
                definition.evaluator_version,
                definition.criticality,
            ):
                raise ValueError("unsupported criterion definition")
            codes = (
                _ERROR_CODES
                if item.status is CriterionStatus.ERROR
                else _CRITERION_CODES[item.criterion_id].get(item.status, set())
            )
            if (
                len(item.evidence.reason_codes) != 1
                or item.evidence.reason_codes[0] not in codes
                or item.evidence.source_count > 2**63 - 1
                or item.evidence.citation_count > 2**63 - 1
            ):
                raise ValueError("invalid criterion evidence")
            code = item.evidence.reason_codes[0]
            if item.criterion_id in {"authorized-source", "citation-resolution"}:
                if item.status in {CriterionStatus.PASS, CriterionStatus.FAIL} and (
                    item.evidence.citation_count == 0
                    or (
                        item.status is CriterionStatus.PASS
                        and item.evidence.source_count == 0
                    )
                ):
                    raise ValueError("citation status contradicts evidence counts")
                if (
                    code
                    in {
                        ReasonCode.CITATION_REQUIRED,
                        ReasonCode.GENERATED_OUTPUT_UNAVAILABLE,
                    }
                    and item.evidence.citation_count != 0
                ):
                    raise ValueError("unavailable citations contradict evidence counts")
        if not isinstance(self.gate_status, GateStatus) or not isinstance(
            self.blocks, tuple
        ):
            raise ValueError("invalid recorded gate")
        for block in self.blocks:
            if not isinstance(block, GateBlock):
                raise ValueError("invalid recorded block")
            if block.criterion_id is not None and (
                block.criterion_id not in expected
                or block.criterion_version
                != expected[block.criterion_id].criterion_version
            ):
                raise ValueError("invalid blocking criterion reference")
            if block.criterion_id is None:
                if block.reason_code not in {
                    ReasonCode.RESULT_SET_INVALID,
                    ReasonCode.OUTPUT_GATE_INELIGIBLE,
                }:
                    raise ValueError("invalid run-level block")
            else:
                criterion = next(
                    item
                    for item in self.criteria
                    if item.criterion_id == block.criterion_id
                )
                if (
                    (
                        block.reason_code is ReasonCode.EVALUATOR_EXECUTION_ERROR
                        and criterion.status is not CriterionStatus.ERROR
                    )
                    or (
                        block.reason_code is ReasonCode.CRITICAL_CRITERION_NOT_PASS
                        and criterion.status
                        not in {CriterionStatus.FAIL, CriterionStatus.UNKNOWN}
                    )
                    or block.reason_code
                    not in {
                        ReasonCode.EVALUATOR_EXECUTION_ERROR,
                        ReasonCode.CRITICAL_CRITERION_NOT_PASS,
                    }
                ):
                    raise ValueError("block contradicts criterion")
        if len(self.blocks) > len(expected) + 2 or len(set(self.blocks)) != len(
            self.blocks
        ):
            raise ValueError("duplicate gate blocks")
        invalid_set = any(
            block.reason_code is ReasonCode.RESULT_SET_INVALID for block in self.blocks
        )
        referenced = {
            block.criterion_id
            for block in self.blocks
            if block.criterion_id is not None
        }
        if (invalid_set and referenced) or (
            not invalid_set
            and any(
                item.status is not CriterionStatus.PASS
                and item.criterion_id not in referenced
                for item in self.criteria
            )
        ):
            raise ValueError("inconsistent recorded block references")
        # Reject contradictory serialization; never derive or repair a gate here.
        if (self.gate_status is GateStatus.PASS) != (not self.blocks):
            raise ValueError("contradictory recorded gate")
        if self.gate_status is GateStatus.PASS and any(
            item.status is not CriterionStatus.PASS for item in self.criteria
        ):
            raise ValueError("passing gate contradicts critical criteria")

    @classmethod
    def from_result(
        cls, result: EvaluationResult, evaluated_at: datetime
    ) -> EvaluationSnapshot:
        if not isinstance(result, EvaluationResult):
            raise TypeError("snapshot requires an actual EvaluationResult")
        return cls(
            result.run_id,
            "1",
            evaluated_at,
            result.task_id,
            result.task_version,
            result.rubric_id,
            result.rubric_version,
            result.criteria,
            result.gate.status,
            result.gate.blocks,
        )

    def validate_run(self, run: RunProvenance) -> None:
        if self.run_id != run.run_id or self.evaluated_at < run.completed_at:
            raise ValueError("evaluation does not match run")
        if any(
            item.evidence.source_count != len(run.sources) for item in self.criteria
        ):
            raise ValueError("evaluation source evidence does not match run")
        for item in self.criteria:
            code = item.evidence.reason_codes[0]
            if (
                code is ReasonCode.GENERATED_OUTPUT_UNAVAILABLE
                and run.status is RunStatus.GENERATED
            ) or (
                code is ReasonCode.CITATION_REQUIRED
                and run.status is not RunStatus.GENERATED
            ):
                raise ValueError("citation evidence contradicts terminal run")
        counts = {item.evidence.citation_count for item in self.criteria}
        if len(counts) != 1:
            raise ValueError("inconsistent citation evidence")
        ineligible = any(
            block.reason_code is ReasonCode.OUTPUT_GATE_INELIGIBLE
            for block in self.blocks
        )
        if ineligible != (run.status is not RunStatus.GENERATED):
            raise ValueError("gate eligibility metadata contradicts run")
        if run.status is not RunStatus.GENERATED and (
            self.gate_status is not GateStatus.BLOCK or counts != {0}
        ):
            raise ValueError("evaluation contradicts terminal run")


class ReviewDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_REVISION = "REQUEST_REVISION"


@dataclass(frozen=True, slots=True)
class HumanReview:
    run_id: RunId
    decision: ReviewDecision
    reviewed_at: datetime
    reviewer_id: str = SYNTHETIC_REVIEWER

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, RunId) or not isinstance(
            self.decision, ReviewDecision
        ):
            raise TypeError("invalid human review")
        if self.reviewer_id != SYNTHETIC_REVIEWER:
            raise ValueError("only the fixed local demo reviewer is supported")
        object.__setattr__(self, "reviewed_at", _timestamp(self.reviewed_at))


class InvalidEvidence(ValueError):
    """Stored evidence cannot be safely reconstructed."""


class ReviewConflict(ValueError):
    """Decision is ineligible or already recorded."""


class RunNotFound(LookupError):
    """No finalized run exists for this identifier."""


class RunEvidenceStore(Protocol):
    """DSL-114 evidence port; leaves the DSL-111 provenance port unchanged."""

    def append_evaluation(self, snapshot: EvaluationSnapshot) -> None: ...
    def get_evaluation(self, run_id: RunId) -> EvaluationSnapshot | None: ...
    def append_review(self, review: HumanReview) -> None: ...
    def get_review(self, run_id: RunId) -> HumanReview | None: ...
    def recent_run_ids(self) -> tuple[RunId, ...]: ...


@dataclass(frozen=True, slots=True)
class RunReviewView:
    run: RunProvenance
    evaluation: EvaluationSnapshot | None
    review: HumanReview | None
    review_state: str
    allowed_decisions: tuple[ReviewDecision, ...]


class RunReviewService:
    """Application-owned completion, read projection and human-review eligibility."""

    def __init__(
        self,
        provenance: ProvenanceStore,
        evidence: RunEvidenceStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._provenance = provenance
        self._evidence = evidence
        self._clock = clock

    def execute(
        self,
        service: RunService,
        *,
        context: SyntheticRequestContext,
        task_text: str,
        query: str,
    ) -> tuple[RunOutcome, RunReviewView]:
        outcome = service.run(context=context, task_text=task_text, query=query)
        run = self._provenance.get(outcome.run_id)
        if run is None:
            raise RunNotFound
        try:
            result = evaluate(EvaluationInput(outcome, run))
            snapshot = EvaluationSnapshot.from_result(result, self._clock())
            snapshot.validate_run(run)
            self._evidence.append_evaluation(snapshot)
        except Exception:
            # The terminal run is already immutable. Never retry or invent evidence.
            return outcome, RunReviewView(run, None, None, "NOT REVIEWABLE", ())
        return outcome, self._view(run)

    def get(self, run_id: RunId) -> RunReviewView:
        run = self._provenance.get(run_id)
        if run is None:
            raise RunNotFound
        return self._view(run)

    def recent(self) -> tuple[RunReviewView, ...]:
        return tuple(self.get(run_id) for run_id in self._evidence.recent_run_ids())

    def _view(self, run: RunProvenance) -> RunReviewView:
        try:
            evaluation = self._evidence.get_evaluation(run.run_id)
            if evaluation is not None:
                evaluation.validate_run(run)
            review = self._evidence.get_review(run.run_id)
            if review is not None and (
                review.run_id != run.run_id
                or evaluation is None
                or review.reviewed_at < evaluation.evaluated_at
                or run.status is not RunStatus.GENERATED
                or (
                    review.decision is ReviewDecision.APPROVE
                    and evaluation.gate_status is not GateStatus.PASS
                )
            ):
                raise InvalidEvidence("inconsistent review evidence")
        except (InvalidEvidence, ValueError, TypeError):
            return RunReviewView(run, None, None, "NOT REVIEWABLE", ())
        if review is not None:
            return RunReviewView(run, evaluation, review, review.decision.value, ())
        if evaluation is None or run.status is not RunStatus.GENERATED:
            return RunReviewView(run, evaluation, None, "NOT REVIEWABLE", ())
        decisions: tuple[ReviewDecision, ...] = (
            ReviewDecision.REJECT,
            ReviewDecision.REQUEST_REVISION,
        )
        if evaluation.gate_status is GateStatus.PASS:
            decisions = (ReviewDecision.APPROVE, *decisions)
        return RunReviewView(run, evaluation, None, "PENDING", decisions)

    def decide(self, run_id: RunId, decision: ReviewDecision) -> HumanReview:
        if not isinstance(decision, ReviewDecision):
            raise TypeError("decision must be ReviewDecision")
        view = self.get(run_id)
        if decision not in view.allowed_decisions:
            raise ReviewConflict("human decision is unavailable")
        review = HumanReview(run_id, decision, self._clock())
        assert view.evaluation is not None
        if review.reviewed_at < view.evaluation.evaluated_at:
            raise ReviewConflict("review timestamp precedes evaluation")
        self._evidence.append_review(review)
        return review
