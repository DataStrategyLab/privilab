from __future__ import annotations

from datetime import UTC, datetime

from privilab.application import (
    ModelRequest,
    RunConfiguration,
    RunId,
    RunProvenance,
    RunService,
    parse_permission_policy,
)
from privilab.domain import (
    AccessScope,
    ResearchResult,
    RetrievedChunk,
    SyntheticRequestContext,
)
from privilab.evals import EvaluationInput, GateStatus, evaluate
from privilab.web.preview import (
    CONTEXT_CHOICES,
    QUERY,
    STANDARD_CONTEXT,
    TASK_TEXT,
    open_preview_run,
)


class _Store:
    def __init__(self) -> None:
        self.record: RunProvenance | None = None

    def append(self, provenance: RunProvenance) -> None:
        self.record = provenance

    def get(self, run_id: RunId) -> RunProvenance | None:
        return (
            self.record
            if self.record is not None and self.record.run_id == run_id
            else None
        )


class _FailingRetrieval:
    def retrieve(
        self,
        query: str,
        access_scope: AccessScope,
        *,
        limit: int = 10,
    ) -> tuple[RetrievedChunk, ...]:
        raise RuntimeError("synthetic retrieval failure")


class _UnusedModel:
    def generate(self, request: ModelRequest) -> ResearchResult:
        raise AssertionError("model must not run after retrieval failure")


def _blocked_context() -> SyntheticRequestContext:
    return next(
        context for key, _label, context in CONTEXT_CHOICES if key == "blocked-role"
    )


def test_governed_dsl_111_generated_run_and_persisted_provenance_pass_gate() -> None:
    with open_preview_run() as (service, store):
        outcome = service.run(
            context=STANDARD_CONTEXT, task_text=TASK_TEXT, query=QUERY
        )
        provenance = store.get(outcome.run_id)
        assert provenance is not None
        result = evaluate(EvaluationInput(outcome, provenance))
    assert result.gate.status is GateStatus.PASS


def test_governed_dsl_111_permission_stop_is_recorded_but_not_output_eligible() -> None:
    with open_preview_run() as (service, store):
        outcome = service.run(
            context=_blocked_context(), task_text=TASK_TEXT, query=QUERY
        )
        provenance = store.get(outcome.run_id)
        assert provenance is not None
        result = evaluate(EvaluationInput(outcome, provenance))
    assert result.gate.status is GateStatus.BLOCK
    assert (
        next(
            item
            for item in result.criteria
            if item.criterion_id == "permission-boundary"
        ).status.value
        == "PASS"
    )


def test_dsl_111_failed_run_is_not_output_eligible() -> None:
    policy = parse_permission_policy(
        {
            "schema_version": 1,
            "policy_id": "integration-evaluation-policy",
            "policy_version": "1.0.0",
            "synthetic": True,
            "required_context": [
                "user_id",
                "role_id",
                "client_id",
                "matter_id",
                "workflow_id",
            ],
            "rules": [
                {
                    "rule_id": "allow-standard",
                    "effect": "ALLOW",
                    "match": {
                        "user_id": "synthetic-user-001",
                        "role_id": "synthetic-researcher",
                        "client_id": "synthetic-client-001",
                        "matter_id": "synthetic-matter-001",
                        "workflow_id": "synthetic-workflow-001",
                    },
                    "condition_ids": [],
                }
            ],
        }
    )
    store = _Store()
    service = RunService._from_components_for_testing(
        policy=policy,
        retrieval_provider=_FailingRetrieval(),
        model_provider=_UnusedModel(),
        provenance_store=store,
        configuration=RunConfiguration(
            configuration_id="evaluation-integration",
            configuration_version="1.0.0",
            provider_id="fixture",
            provider_version="1",
            model_id="fixture",
            model_version="1",
            retrieval_provider_id="failing",
            retrieval_provider_version="1",
        ),
        run_id_factory=lambda: RunId("evaluation-failed-run"),
        clock=lambda: datetime(2026, 9, 20, tzinfo=UTC),
    )
    outcome = service.run(context=STANDARD_CONTEXT, task_text=TASK_TEXT, query=QUERY)
    assert store.record is not None
    result = evaluate(EvaluationInput(outcome, store.record))
    assert result.gate.status is GateStatus.BLOCK
