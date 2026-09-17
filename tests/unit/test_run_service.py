from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from unittest.mock import Mock

import pytest

from privilab.application import (
    ContextProvenance,
    FailureStage,
    ModelRequest,
    PermissionPolicy,
    PermissionStopReason,
    RunConfiguration,
    RunId,
    RunProvenance,
    RunService,
    RunStatus,
    access_scope_for,
    evaluate_permission,
    governed_configuration_hash,
    parse_permission_policy,
)
from privilab.application import run_service as run_module
from privilab.domain import (
    AccessScope,
    ChunkId,
    CitationReference,
    ClientContext,
    MatterContext,
    PermissionState,
    ResearchResult,
    RetrievedChunk,
    Role,
    SourceId,
    SyntheticRequestContext,
    UserContext,
    UserIdentity,
    WorkflowContext,
)


def context() -> SyntheticRequestContext:
    return SyntheticRequestContext(
        user=UserContext(UserIdentity("user-a"), Role("role-a")),
        client=ClientContext("client-a"),
        matter=MatterContext("matter-a"),
        workflow=WorkflowContext("workflow-a"),
    )


def policy_for(
    effect: str = "ALLOW",
    *,
    match: dict[str, str] | None = None,
    condition_ids: list[str] | None = None,
    version: str = "1.0.0",
) -> PermissionPolicy:
    return parse_permission_policy(
        {
            "schema_version": 1,
            "policy_id": "run-policy",
            "policy_version": version,
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
                    "rule_id": "run-rule",
                    "effect": effect,
                    "match": (
                        {
                            "user_id": "user-a",
                            "role_id": "role-a",
                            "client_id": "client-a",
                            "matter_id": "matter-a",
                            "workflow_id": "workflow-a",
                        }
                        if match is None
                        else match
                    ),
                    "condition_ids": condition_ids or [],
                }
            ],
        }
    )


def configuration(
    *,
    options: tuple[tuple[str, str], ...] = (
        (
            "fixture_manifest",
            "privilab.adapters.models:resources/governed_fixtures/manifest.json",
        ),
        ("response_format", "research-result-v1"),
    ),
) -> RunConfiguration:
    return RunConfiguration(
        configuration_id="p0-run-configuration",
        configuration_version="1.0.0",
        provider_id="fixture-model-provider",
        provider_version="1",
        model_id="model-output.synthetic-happy-path.001",
        model_version="1.0.0",
        retrieval_provider_id="sqlite-fts5",
        retrieval_provider_version="1",
        retrieval_limit=5,
        options=options,
    )


class MemoryProvenanceStore:
    def __init__(self) -> None:
        self.records: dict[RunId, RunProvenance] = {}

    def append(self, provenance: RunProvenance) -> None:
        if provenance.run_id in self.records:
            raise ValueError("duplicate run ID")
        self.records[provenance.run_id] = provenance

    def get(self, run_id: RunId) -> RunProvenance | None:
        return self.records.get(run_id)


class RetrievalSpy:
    def __init__(
        self,
        chunks: tuple[RetrievedChunk, ...] = (),
        events: list[str] | None = None,
    ) -> None:
        self.chunks = chunks
        self.calls: list[tuple[str, AccessScope, int]] = []
        self.events = events

    def retrieve(
        self,
        query: str,
        access_scope: AccessScope,
        *,
        limit: int = 10,
    ) -> tuple[RetrievedChunk, ...]:
        self.calls.append((query, access_scope, limit))
        if self.events is not None:
            self.events.append("retrieval")
        return self.chunks


class ModelSpy:
    def __init__(
        self,
        result: ResearchResult | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.result = result or ResearchResult("Synthetic answer.")
        self.requests: list[ModelRequest] = []
        self.events = events

    def generate(self, request: ModelRequest) -> ResearchResult:
        self.requests.append(request)
        if self.events is not None:
            self.events.append("model")
        return self.result


class FailingRetrieval(RetrievalSpy):
    def retrieve(
        self,
        query: str,
        access_scope: AccessScope,
        *,
        limit: int = 10,
    ) -> tuple[RetrievedChunk, ...]:
        self.calls.append((query, access_scope, limit))
        raise ValueError("synthetic retrieval failure")


class FailingModel(ModelSpy):
    def generate(self, request: ModelRequest) -> ResearchResult:
        self.requests.append(request)
        raise ValueError("synthetic model failure")


def id_factory(*values: str) -> Callable[[], RunId]:
    identifiers = iter(values)

    def create() -> RunId:
        return RunId(next(identifiers))

    return create


def clock() -> datetime:
    return datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "task", ["   ", "invalid\ud800", 123], ids=["whitespace", "surrogate", "wrong-type"]
)
def test_r06_07_invalid_task_stops_before_protected_progression(
    task: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    retrieval = RetrievalSpy(
        (
            RetrievedChunk(
                SourceId("source"),
                ChunkId("chunk"),
                0,
                "Synthetic title",
                "Synthetic protected text",
                source_version="1",
            ),
        )
    )
    model = ModelSpy()
    store = MemoryProvenanceStore()
    permission = Mock(wraps=evaluate_permission)
    scope = Mock(wraps=access_scope_for)
    identity = Mock(return_value=RunId("invalid"))
    now = Mock(wraps=clock)
    monkeypatch.setattr(run_module, "evaluate_permission", permission)
    monkeypatch.setattr(run_module, "access_scope_for", scope)
    service = RunService._from_components_for_testing(
        policy=policy_for(),
        retrieval_provider=retrieval,
        model_provider=model,
        provenance_store=store,
        configuration=configuration(),
        run_id_factory=identity,
        clock=now,
    )
    with pytest.raises((TypeError, ValueError)) as expected:
        ModelRequest(task, ())
    with pytest.raises(type(expected.value), match=f"^{expected.value}$"):
        service.run(context=context(), task_text=task, query="notice")
    assert retrieval.calls == []
    assert model.requests == []
    assert store.records == {}
    permission.assert_not_called()
    scope.assert_not_called()
    identity.assert_not_called()
    now.assert_not_called()


def timestamp_provenance(started_at: Any, completed_at: Any) -> RunProvenance:
    return RunProvenance(
        run_id=RunId("synthetic-timestamp"),
        started_at=started_at,
        completed_at=completed_at,
        status=RunStatus.FAILED,
        context=ContextProvenance.from_context(context()),
        configuration=configuration(),
        configuration_hash=f"sha256:{'0' * 64}",
        permission=None,
        retrieval_called=False,
        model_called=False,
        failure_stage=FailureStage.PERMISSION,
    )


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (timedelta(), datetime(2026, 9, 16, 12, 0, 0, 123456, UTC)),
        (timedelta(seconds=30), datetime(2026, 9, 16, 11, 59, 30, 123456, UTC)),
        (timedelta(seconds=-30), datetime(2026, 9, 16, 12, 0, 30, 123456, UTC)),
        (
            timedelta(seconds=30, microseconds=123456),
            datetime(2026, 9, 16, 11, 59, 30, 0, UTC),
        ),
        (
            timedelta(seconds=-30, microseconds=-654321),
            datetime(2026, 9, 16, 12, 0, 30, 777777, UTC),
        ),
        (timedelta(hours=5, minutes=30), datetime(2026, 9, 16, 6, 30, 0, 123456, UTC)),
        (
            timedelta(hours=-4, minutes=-15),
            datetime(2026, 9, 16, 16, 15, 0, 123456, UTC),
        ),
    ],
)
def test_review04_provenance_normalizes_offsets_exactly(
    offset: timedelta, expected: datetime
) -> None:
    value = datetime(2026, 9, 16, 12, 0, 0, 123456, timezone(offset))
    record = timestamp_provenance(value, value)
    assert record.started_at == record.completed_at == expected
    assert record.started_at.tzinfo is record.completed_at.tzinfo is UTC


@pytest.mark.parametrize("microseconds", [-1, 0, 1])
def test_review04_provenance_orders_normalized_instants(microseconds: int) -> None:
    instant = datetime(2026, 9, 16, 12, 0, 0, 123456, UTC)
    started = instant.astimezone(timezone(timedelta(seconds=30, microseconds=654321)))
    completed = (instant + timedelta(microseconds=microseconds)).astimezone(
        timezone(timedelta(seconds=-30, microseconds=-123456))
    )
    if microseconds < 0:
        with pytest.raises(
            ValueError, match="^completed_at must not precede started_at$"
        ):
            timestamp_provenance(started, completed)
    else:
        record = timestamp_provenance(started, completed)
        assert record.started_at == instant
        assert record.completed_at == instant + timedelta(microseconds=microseconds)
        assert record.started_at.tzinfo is record.completed_at.tzinfo is UTC


@pytest.mark.parametrize("field", ["started_at", "completed_at"])
@pytest.mark.parametrize("invalid", [None, "2026-09-16", 0, datetime(2026, 9, 16)])
def test_review04_timestamps_require_aware_datetimes(field: str, invalid: Any) -> None:
    values = {"started_at": clock(), "completed_at": clock()}
    values[field] = invalid
    with pytest.raises(
        ValueError, match=f"^{field} must be a timezone-aware datetime$"
    ):
        timestamp_provenance(**values)


@pytest.mark.parametrize("field", ["started_at", "completed_at"])
@pytest.mark.parametrize(
    "invalid",
    [
        datetime.min.replace(tzinfo=timezone(timedelta(microseconds=1))),
        datetime.max.replace(tzinfo=timezone(timedelta(microseconds=-1))),
        datetime.min.replace(tzinfo=timezone(timedelta(hours=23, minutes=59))),
        datetime.max.replace(tzinfo=timezone(timedelta(hours=-23, minutes=-59))),
    ],
)
def test_review04_utc_conversion_overflow_is_field_specific(
    field: str, invalid: datetime
) -> None:
    values = {"started_at": clock(), "completed_at": clock()}
    values[field] = invalid
    with pytest.raises(
        ValueError, match=f"^{field} must be representable in UTC$"
    ) as caught:
        timestamp_provenance(**values)
    assert isinstance(caught.value.__cause__, OverflowError)


@pytest.mark.parametrize(
    "value",
    [
        datetime.min.replace(tzinfo=UTC),
        datetime.max.replace(tzinfo=UTC),
        datetime(1, 1, 1, 0, 0, 0, 1, timezone(timedelta(microseconds=1))),
        datetime(
            9999, 12, 31, 23, 59, 59, 999998, timezone(timedelta(microseconds=-1))
        ),
    ],
)
def test_review04_utc_representability_is_inclusive(value: datetime) -> None:
    record = timestamp_provenance(value, value)
    assert record.started_at == record.completed_at == value.astimezone(UTC)
    assert record.started_at.tzinfo is record.completed_at.tzinfo is UTC


@pytest.mark.parametrize(
    ("policy", "expected_state", "expected_reason", "expected_conditions"),
    [
        (
            policy_for("BLOCK"),
            PermissionState.BLOCK,
            PermissionStopReason.BLOCK,
            (),
        ),
        (
            policy_for("ALLOW", match={"user_id": "other-user"}),
            PermissionState.UNKNOWN,
            PermissionStopReason.UNKNOWN,
            (),
        ),
        (
            policy_for("ALLOW", condition_ids=["condition-review"]),
            PermissionState.CONDITIONAL,
            PermissionStopReason.UNRESOLVED_CONDITIONS,
            ("condition-review",),
        ),
    ],
)
def test_fail_closed_decisions_persist_without_retrieval_or_model(
    policy: PermissionPolicy,
    expected_state: PermissionState,
    expected_reason: PermissionStopReason,
    expected_conditions: tuple[str, ...],
) -> None:
    retrieval = RetrievalSpy()
    model = ModelSpy()
    store = MemoryProvenanceStore()
    service = RunService._from_components_for_testing(
        policy=policy,
        retrieval_provider=retrieval,
        model_provider=model,
        provenance_store=store,
        configuration=configuration(),
        run_id_factory=id_factory("run-stopped"),
        clock=clock,
    )

    outcome = service.run(
        context=context(),
        task_text="Summarize the synthetic material.",
        query="synthetic",
    )

    assert outcome.status is RunStatus.PERMISSION_STOPPED
    assert outcome.permission_result is not None
    assert outcome.permission_result.state is expected_state
    assert retrieval.calls == []
    assert model.requests == []
    persisted = store.get(outcome.run_id)
    assert persisted is not None
    assert persisted.stop_reason is expected_reason
    assert persisted.permission is not None
    assert persisted.permission.policy_id == "run-policy"
    assert persisted.permission.policy_version == "1.0.0"
    assert persisted.permission.unresolved_condition_ids == expected_conditions
    assert persisted.sources == ()
    assert persisted.retrieval_called is False
    assert persisted.model_called is False


def test_allowed_run_maps_only_exact_retrieval_output_before_model_call() -> None:
    events: list[str] = []
    returned = (
        RetrievedChunk(
            SourceId("source-a"),
            ChunkId("chunk-a"),
            0,
            "Synthetic A",
            "authorized alpha",
            source_version="2.0.0",
        ),
        RetrievedChunk(
            SourceId("source-b"),
            ChunkId("chunk-b"),
            0,
            "Synthetic B",
            "authorized beta",
            source_version="3.1.0",
        ),
        RetrievedChunk(
            SourceId("source-a"),
            ChunkId("chunk-a-two"),
            1,
            "Synthetic A",
            "authorized alpha two",
            source_version="2.0.0",
        ),
    )
    retrieval = RetrievalSpy(returned, events)
    model = ModelSpy(
        ResearchResult(
            "Untrusted structured output.",
            (CitationReference("not-returned", "model-chosen"),),
        ),
        events,
    )
    store = MemoryProvenanceStore()
    service = RunService._from_components_for_testing(
        policy=policy_for(),
        retrieval_provider=retrieval,
        model_provider=model,
        provenance_store=store,
        configuration=configuration(),
        run_id_factory=id_factory("run-allowed"),
        clock=clock,
    )

    outcome = service.run(
        context=context(),
        task_text="Summarize the exact chunks.",
        query="authorized",
    )

    assert outcome.status is RunStatus.GENERATED
    assert events == ["retrieval", "model"]
    assert len(retrieval.calls) == 1
    retrieval_scope = retrieval.calls[0][1]
    assert isinstance(retrieval_scope, AccessScope)
    assert retrieval_scope.user_id == "user-a"
    assert len(model.requests) == 1
    assert [
        (chunk.source_id, chunk.chunk_id, chunk.text)
        for chunk in model.requests[0].source_chunks
    ] == [
        ("source-a", "chunk-a", "authorized alpha"),
        ("source-b", "chunk-b", "authorized beta"),
        ("source-a", "chunk-a-two", "authorized alpha two"),
    ]
    assert all(
        chunk.source_id != "not-returned" for chunk in model.requests[0].source_chunks
    )
    persisted = store.get(outcome.run_id)
    assert persisted is not None
    assert persisted.retrieval_called is True
    assert persisted.model_called is True
    assert [
        (
            source.source_id,
            source.source_version,
            tuple(chunk.chunk_id for chunk in source.chunks),
        )
        for source in persisted.sources
    ] == [
        ("source-a", "2.0.0", ("chunk-a", "chunk-a-two")),
        ("source-b", "3.1.0", ("chunk-b",)),
    ]
    assert [
        (source_id, chunk.chunk_id, chunk.ordinal, chunk.retrieval_position)
        for source_id, _source_version, chunk in (persisted.chunks_in_retrieval_order)
    ] == [
        ("source-a", "chunk-a", 0, 0),
        ("source-b", "chunk-b", 0, 1),
        ("source-a", "chunk-a-two", 1, 2),
    ]
    assert all(source.source_id != "not-returned" for source in persisted.sources)


def test_rerun_appends_new_immutable_identity_and_preserves_first_record() -> None:
    store = MemoryProvenanceStore()
    service = RunService._from_components_for_testing(
        policy=policy_for(),
        retrieval_provider=RetrievalSpy(),
        model_provider=ModelSpy(),
        provenance_store=store,
        configuration=configuration(),
        run_id_factory=id_factory("run-first", "run-second"),
        clock=clock,
    )

    first = service.run(context=context(), task_text="Synthetic task.", query="first")
    first_record = store.get(first.run_id)
    second = service.run(
        context=context(),
        task_text="Synthetic task.",
        query="first",
    )

    assert first.run_id != second.run_id
    assert len(store.records) == 2
    assert store.get(first.run_id) == first_record
    with pytest.raises(FrozenInstanceError):
        first.run_id.value = "changed"  # type: ignore[misc]


def test_authorization_failure_records_no_provider_calls() -> None:
    minimal_policy = parse_permission_policy(
        {
            "schema_version": 1,
            "policy_id": "minimal-run-policy",
            "policy_version": "1.0.0",
            "synthetic": True,
            "required_context": ["user_id"],
            "rules": [
                {
                    "rule_id": "allow-user",
                    "effect": "ALLOW",
                    "match": {"user_id": "user-a"},
                    "condition_ids": [],
                }
            ],
        }
    )
    retrieval = RetrievalSpy()
    model = ModelSpy()
    store = MemoryProvenanceStore()
    service = RunService._from_components_for_testing(
        policy=minimal_policy,
        retrieval_provider=retrieval,
        model_provider=model,
        provenance_store=store,
        configuration=configuration(),
        run_id_factory=id_factory("run-authorization-failed"),
        clock=clock,
    )

    outcome = service.run(
        context=SyntheticRequestContext(
            user=UserContext(identity=UserIdentity("user-a"))
        ),
        task_text="Synthetic task.",
        query="synthetic",
    )

    assert outcome.status is RunStatus.FAILED
    assert outcome.failure_stage is FailureStage.AUTHORIZATION
    assert retrieval.calls == []
    assert model.requests == []
    persisted = store.get(outcome.run_id)
    assert persisted is not None
    assert persisted.retrieval_called is False
    assert persisted.model_called is False


def test_retrieval_failure_is_persisted_and_cannot_reach_model() -> None:
    retrieval = FailingRetrieval()
    model = ModelSpy()
    store = MemoryProvenanceStore()
    service = RunService._from_components_for_testing(
        policy=policy_for(),
        retrieval_provider=retrieval,
        model_provider=model,
        provenance_store=store,
        configuration=configuration(),
        run_id_factory=id_factory("run-failed"),
        clock=clock,
    )

    outcome = service.run(
        context=context(),
        task_text="Synthetic task.",
        query="malformed",
    )

    assert outcome.status is RunStatus.FAILED
    assert outcome.failure_stage is FailureStage.RETRIEVAL
    assert len(retrieval.calls) == 1
    assert model.requests == []
    persisted = store.get(outcome.run_id)
    assert persisted is not None
    assert persisted.failure_stage is FailureStage.RETRIEVAL
    assert persisted.retrieval_called is True
    assert persisted.model_called is False
    with pytest.raises(ValueError, match="failure stage"):
        replace(persisted, retrieval_called=False)


def test_malformed_permission_input_fails_before_retrieval() -> None:
    retrieval = RetrievalSpy()
    model = ModelSpy()
    store = MemoryProvenanceStore()
    service = RunService._from_components_for_testing(
        policy=policy_for(),
        retrieval_provider=retrieval,
        model_provider=model,
        provenance_store=store,
        configuration=configuration(),
        run_id_factory=id_factory("run-permission-error"),
        clock=clock,
    )

    outcome = service.run(
        context=context(),
        task_text="Synthetic task.",
        query="synthetic",
        satisfied_conditions=set(),  # type: ignore[arg-type]
    )

    assert outcome.status is RunStatus.FAILED
    assert outcome.failure_stage is FailureStage.PERMISSION
    assert retrieval.calls == []
    assert model.requests == []
    persisted = store.get(outcome.run_id)
    assert persisted is not None
    assert persisted.retrieval_called is False
    assert persisted.model_called is False


def test_model_failure_retains_only_trusted_retrieval_and_execution_metadata() -> None:
    retrieved = (
        RetrievedChunk(
            SourceId("source-a"),
            ChunkId("chunk-a"),
            0,
            "Synthetic source",
            "Synthetic source text.",
            source_version="1.0.0",
        ),
    )
    retrieval = RetrievalSpy(retrieved)
    model = FailingModel()
    store = MemoryProvenanceStore()
    service = RunService._from_components_for_testing(
        policy=policy_for(),
        retrieval_provider=retrieval,
        model_provider=model,
        provenance_store=store,
        configuration=configuration(),
        run_id_factory=id_factory("run-model-failed"),
        clock=clock,
    )

    outcome = service.run(
        context=context(),
        task_text="Synthetic task.",
        query="synthetic",
    )

    assert outcome.status is RunStatus.FAILED
    assert outcome.failure_stage is FailureStage.MODEL
    assert len(model.requests) == 1
    persisted = store.get(outcome.run_id)
    assert persisted is not None
    assert persisted.retrieval_called is True
    assert persisted.model_called is True
    assert persisted.failure_stage is FailureStage.MODEL
    assert persisted.sources[0].chunks[0].chunk_id == "chunk-a"


def test_configuration_hash_is_canonical_and_changes_with_governed_input() -> None:
    first = configuration(options=(("zeta", "2"), ("alpha", "1")))
    reordered = configuration(options=(("alpha", "1"), ("zeta", "2")))
    policy = policy_for()

    assert first.options == reordered.options
    assert governed_configuration_hash(first, policy) == governed_configuration_hash(
        reordered,
        policy,
    )
    assert governed_configuration_hash(first, policy) == governed_configuration_hash(
        first,
        policy,
    )
    assert governed_configuration_hash(
        replace(first, retrieval_limit=6),
        policy,
    ) != governed_configuration_hash(first, policy)
    assert governed_configuration_hash(
        replace(first, configuration_version="2.0.0"),
        policy,
    ) != governed_configuration_hash(first, policy)
    assert governed_configuration_hash(first, policy_for(version="2.0.0")) != (
        governed_configuration_hash(first, policy)
    )
    assert governed_configuration_hash(first, policy_for("BLOCK")) != (
        governed_configuration_hash(first, policy)
    )


@pytest.mark.parametrize(
    "changed",
    [
        replace(configuration(), retrieval_provider_id="other-retrieval"),
        replace(configuration(), retrieval_provider_version="2"),
        replace(configuration(), provider_id="other-fixture-provider"),
        replace(configuration(), provider_version="2"),
        replace(configuration(), model_id="model-output.synthetic-other.001"),
        replace(configuration(), model_version="2.0.0"),
        replace(configuration(), model_content_hash=f"sha256:{'a' * 64}"),
    ],
)
def test_configuration_hash_changes_for_provider_or_fixture_identity(
    changed: RunConfiguration,
) -> None:
    baseline = configuration()
    policy = policy_for()

    assert governed_configuration_hash(changed, policy) != (
        governed_configuration_hash(baseline, policy)
    )
