"""Application eligibility is decided before the evidence adapter is called."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, call

import pytest

from privilab.adapters.models import FixtureModelProvider
from privilab.application import RunId, RunProvenance
from privilab.application.run_review import (
    EvaluationSnapshot,
    HumanReview,
    InvalidEvidence,
    ReviewConflict,
    ReviewDecision,
    RunEvidenceStore,
    RunNotFound,
    RunReviewService,
)
from privilab.evals import EvaluationInput, GateStatus, evaluate
from privilab.web.preview import CONTEXT_CHOICES, QUERY, TASK_TEXT, open_preview_run


def completed(choice: str = "standard") -> tuple[RunProvenance, EvaluationSnapshot]:
    context = next(context for key, _, context in CONTEXT_CHOICES if key == choice)
    with open_preview_run(context_choice=choice) as (service, store):
        outcome = service.run(context=context, task_text=TASK_TEXT, query=QUERY)
        run = store.get(outcome.run_id)
        assert run is not None
        result = evaluate(EvaluationInput(outcome, run))
        snapshot = EvaluationSnapshot.from_result(result, datetime.now(UTC))
        assert snapshot.criteria is result.criteria
        assert snapshot.blocks is result.gate.blocks
        assert snapshot.gate_status is result.gate.status
        return run, snapshot


@pytest.mark.parametrize(
    "choice",
    [
        "standard",
        "critical-citation-failure",
        "blocked-role",
        "missing-workflow",
        "conditional-role",
    ],
)
@pytest.mark.parametrize("decision", list(ReviewDecision))
def test_every_scenario_and_decision_is_application_owned(
    choice: str, decision: ReviewDecision
) -> None:
    run, evaluation = completed(choice)
    store = Mock(spec=RunEvidenceStore)
    provenance = Mock()
    provenance.get.return_value = run
    store.get_evaluation.return_value = evaluation
    store.get_review.return_value = None
    clock = evaluation.evaluated_at + timedelta(seconds=1)
    service = RunReviewService(provenance, store, clock=lambda: clock)
    allowed = choice == "standard" or (
        choice == "critical-citation-failure" and decision is not ReviewDecision.APPROVE
    )
    if allowed:
        review = service.decide(run.run_id, decision)
        assert review == HumanReview(run.run_id, decision, clock)
        store.append_review.assert_called_once_with(review)
    else:
        with pytest.raises(ReviewConflict):
            service.decide(run.run_id, decision)
        store.append_review.assert_not_called()
    assert store.mock_calls[:2] == [
        call.get_evaluation(run.run_id),
        call.get_review(run.run_id),
    ]
    provenance.get.assert_called_once_with(run.run_id)


@pytest.mark.parametrize(
    "state", ["missing", "corrupt", "cross-run", "reviewed", "failed"]
)
@pytest.mark.parametrize("decision", list(ReviewDecision))
def test_ineligible_requests_never_append(
    state: str, decision: ReviewDecision, monkeypatch: pytest.MonkeyPatch
) -> None:
    if state == "failed":
        monkeypatch.setattr(
            FixtureModelProvider,
            "generate",
            Mock(side_effect=RuntimeError("private failure")),
        )
    run, evaluation = completed()
    store = Mock(spec=RunEvidenceStore)
    provenance = Mock()
    provenance.get.return_value = run
    store.get_evaluation.return_value = evaluation
    store.get_review.return_value = None
    if state == "missing":
        store.get_evaluation.return_value = None
    elif state == "corrupt":
        store.get_evaluation.side_effect = InvalidEvidence("private invalid data")
    elif state == "cross-run":
        store.get_evaluation.return_value = replace(
            evaluation, run_id=RunId("other-run")
        )
    elif state == "reviewed":
        store.get_review.return_value = HumanReview(
            run.run_id, ReviewDecision.REJECT, evaluation.evaluated_at
        )
    service = RunReviewService(provenance, store)
    with pytest.raises(ReviewConflict):
        service.decide(run.run_id, decision)
    store.append_review.assert_not_called()


def test_missing_run_is_distinct_and_stops_before_evidence() -> None:
    provenance = Mock()
    provenance.get.return_value = None
    store = Mock(spec=RunEvidenceStore)
    with pytest.raises(RunNotFound):
        RunReviewService(provenance, store).decide(
            RunId("missing"), ReviewDecision.REJECT
        )
    assert store.mock_calls == []


def test_snapshot_is_actual_metadata_and_pass_is_not_a_human_decision() -> None:
    run, evaluation = completed()
    evaluation.validate_run(run)
    assert evaluation.gate_status is GateStatus.PASS
    assert not hasattr(evaluation, "answer_text")
    assert not hasattr(evaluation, "evaluation_id")
    store = Mock(spec=RunEvidenceStore)
    store.get_evaluation.return_value = evaluation
    store.get_review.return_value = None
    provenance = Mock()
    provenance.get.return_value = run
    view = RunReviewService(provenance, store).get(run.run_id)
    assert view.review_state == "PENDING"
    assert view.review is None
    store.append_review.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        "run-id",
        "source-count",
        "timestamp",
        "citation-count",
        "gate",
        "criterion-version",
        "reason",
    ],
)
def test_snapshots_reject_malformed_or_contradictory_evidence(change: str) -> None:
    run, original = completed()
    with pytest.raises(ValueError):
        snapshot = original
        if change == "run-id":
            snapshot = replace(original, run_id=RunId("other"))
        elif change == "source-count":
            item = original.criteria[0]
            snapshot = replace(
                original,
                criteria=(
                    replace(item, evidence=replace(item.evidence, source_count=9)),
                    *original.criteria[1:],
                ),
            )
        elif change == "citation-count":
            item = original.criteria[0]
            snapshot = replace(
                original,
                criteria=(
                    replace(item, evidence=replace(item.evidence, citation_count=9)),
                    *original.criteria[1:],
                ),
            )
        elif change == "timestamp":
            snapshot = replace(
                original, evaluated_at=run.started_at - timedelta(seconds=1)
            )
        elif change == "gate":
            snapshot = replace(original, gate_status=GateStatus.BLOCK)
        elif change == "criterion-version":
            snapshot = replace(
                original,
                criteria=(
                    replace(original.criteria[0], evaluator_version="99"),
                    *original.criteria[1:],
                ),
            )
        else:
            snapshot = replace(
                original,
                criteria=(
                    replace(
                        original.criteria[0], evidence=original.criteria[1].evidence
                    ),
                    *original.criteria[1:],
                ),
            )
        snapshot.validate_run(run)


def test_passing_snapshot_cannot_report_zero_citations() -> None:
    _, snapshot = completed()
    with pytest.raises(ValueError, match="citation status contradicts"):
        replace(
            snapshot,
            criteria=tuple(
                replace(item, evidence=replace(item.evidence, citation_count=0))
                for item in snapshot.criteria
            ),
        )


def test_blocked_snapshot_cannot_omit_a_failing_criterion_reference() -> None:
    _, snapshot = completed("critical-citation-failure")
    assert len(snapshot.blocks) > 1
    with pytest.raises(ValueError, match="block references"):
        replace(snapshot, blocks=snapshot.blocks[:1])


@pytest.mark.parametrize(
    "timestamp", ["0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59.999999-23:59"]
)
def test_evidence_timestamps_reject_utc_overflow_as_invalid_data(
    timestamp: str,
) -> None:
    run, snapshot = completed()
    invalid = datetime.fromisoformat(timestamp)
    with pytest.raises(ValueError, match="supported UTC range"):
        replace(snapshot, evaluated_at=invalid)
    with pytest.raises(ValueError, match="supported UTC range"):
        HumanReview(run.run_id, ReviewDecision.REJECT, invalid)
