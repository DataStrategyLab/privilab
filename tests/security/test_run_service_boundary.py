from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from privilab.adapters.retrieval import SQLiteFtsRetrievalProvider
from privilab.application import (
    FailureStage,
    ModelRequest,
    PermissionPolicy,
    RunConfiguration,
    RunId,
    RunProvenance,
    RunService,
    RunStatus,
    parse_permission_policy,
)
from privilab.domain import (
    AccessScope,
    ChunkId,
    CitationReference,
    ClientContext,
    MatterContext,
    PermissionState,
    ResearchResult,
    RetrievalChunk,
    RetrievalSource,
    RetrievedChunk,
    Role,
    SourceEntitlement,
    SourceId,
    SyntheticRequestContext,
    UserContext,
    UserIdentity,
    WorkflowContext,
)


def context(
    user_id: str,
    *,
    include_role: bool = True,
) -> SyntheticRequestContext:
    return SyntheticRequestContext(
        user=UserContext(
            UserIdentity(user_id),
            Role("role-a") if include_role else None,
        ),
        client=ClientContext("client-a"),
        matter=MatterContext("matter-a"),
        workflow=WorkflowContext("workflow-a"),
    )


def allow_complete_context_policy() -> PermissionPolicy:
    return parse_permission_policy(
        {
            "schema_version": 1,
            "policy_id": "security-run-policy",
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
                    "rule_id": "allow-complete-synthetic-context",
                    "effect": "ALLOW",
                    "match": {},
                    "condition_ids": [],
                }
            ],
        }
    )


def configuration() -> RunConfiguration:
    return RunConfiguration(
        configuration_id="p0-security-run",
        configuration_version="1.0.0",
        provider_id="fixture-model-provider",
        provider_version="1",
        model_id="security-model-output",
        model_version="1.0.0",
        retrieval_provider_id="sqlite-fts5",
        retrieval_provider_version="1",
        retrieval_limit=10,
    )


def protected_source(
    source_name: str,
    text: str,
    *,
    entitled_user: str | None,
) -> RetrievalSource:
    source_id = SourceId(source_name)
    entitlements = (
        ()
        if entitled_user is None
        else (
            SourceEntitlement(
                source_id,
                entitled_user,
                "role-a",
                "client-a",
                "matter-a",
                "workflow-a",
            ),
        )
    )
    return RetrievalSource(
        source_id,
        f"Synthetic {source_name}",
        (
            RetrievalChunk(
                ChunkId(f"{source_name}.chunk-000"),
                source_id,
                0,
                text,
            ),
        ),
        entitlements,
        source_version="1.0.0",
    )


class CountingRetrieval:
    def __init__(self, provider: SQLiteFtsRetrievalProvider) -> None:
        self.provider = provider
        self.calls: list[AccessScope] = []

    def retrieve(
        self,
        query: str,
        access_scope: AccessScope,
        *,
        limit: int = 10,
    ) -> tuple[RetrievedChunk, ...]:
        self.calls.append(access_scope)
        return self.provider.retrieve(query, access_scope, limit=limit)


class CapturingModel:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ResearchResult:
        self.requests.append(request)
        return ResearchResult(
            "Untrusted result metadata cannot expand provenance.",
            (CitationReference("source-unauthorized", "model-selected-chunk"),),
        )


class MemoryStore:
    def __init__(self) -> None:
        self.records: dict[RunId, RunProvenance] = {}

    def append(self, provenance: RunProvenance) -> None:
        if provenance.run_id in self.records:
            raise ValueError("duplicate run ID")
        self.records[provenance.run_id] = provenance

    def get(self, run_id: RunId) -> RunProvenance | None:
        return self.records.get(run_id)


def id_factory() -> Callable[[], RunId]:
    values = iter(("security-run-a", "security-run-b", "security-run-error"))
    return lambda: RunId(next(values))


def test_run_service_preserves_cross_context_retrieval_isolation(
    tmp_path: Path,
) -> None:
    provider = SQLiteFtsRetrievalProvider(tmp_path / "security-run.sqlite3")
    provider.index_source(
        protected_source(
            "source-a",
            "boundarytoken authorized text for user a",
            entitled_user="user-a",
        )
    )
    provider.index_source(
        protected_source(
            "source-b",
            "boundarytoken unauthorized secret for user a",
            entitled_user="user-b",
        )
    )
    provider.index_source(
        protected_source(
            "source-missing-entitlement",
            "boundarytoken unentitled content",
            entitled_user=None,
        )
    )
    retrieval = CountingRetrieval(provider)
    model = CapturingModel()
    store = MemoryStore()
    service = RunService._from_components_for_testing(
        policy=allow_complete_context_policy(),
        retrieval_provider=retrieval,
        model_provider=model,
        provenance_store=store,
        configuration=configuration(),
        run_id_factory=id_factory(),
    )
    try:
        user_a = service.run(
            context=context("user-a"),
            task_text="Use only the authorized synthetic source.",
            query="boundarytoken",
        )
        user_b = service.run(
            context=context("user-b"),
            task_text="Use only the authorized synthetic source.",
            query="boundarytoken",
        )
        malformed = service.run(
            context=context("user-a"),
            task_text="Malformed retrieval must fail safely.",
            query='"unterminated',
        )
    finally:
        provider.close()

    assert user_a.status is RunStatus.GENERATED
    assert user_b.status is RunStatus.GENERATED
    assert [chunk.source_id for chunk in model.requests[0].source_chunks] == [
        "source-a"
    ]
    assert [chunk.source_id for chunk in model.requests[1].source_chunks] == [
        "source-b"
    ]
    assert all(
        "unentitled" not in chunk.text
        for request in model.requests
        for chunk in request.source_chunks
    )
    assert [scope.user_id for scope in retrieval.calls[:2]] == ["user-a", "user-b"]
    persisted_a = store.get(user_a.run_id)
    assert persisted_a is not None
    assert persisted_a.retrieval_called is True
    assert persisted_a.model_called is True
    assert [source.source_id for source in persisted_a.sources] == ["source-a"]
    assert all(
        source.source_id != "source-unauthorized" for source in persisted_a.sources
    )
    assert malformed.status is RunStatus.FAILED
    assert malformed.failure_stage is FailureStage.RETRIEVAL
    assert len(model.requests) == 2
    malformed_record = store.get(malformed.run_id)
    assert malformed_record is not None
    assert malformed_record.retrieval_called is True
    assert malformed_record.model_called is False


def test_missing_material_context_stops_before_retrieval_or_model(
    tmp_path: Path,
) -> None:
    provider = SQLiteFtsRetrievalProvider(tmp_path / "missing-context.sqlite3")
    retrieval = CountingRetrieval(provider)
    model = CapturingModel()
    store = MemoryStore()
    service = RunService._from_components_for_testing(
        policy=allow_complete_context_policy(),
        retrieval_provider=retrieval,
        model_provider=model,
        provenance_store=store,
        configuration=configuration(),
        run_id_factory=lambda: RunId("missing-context-run"),
    )
    try:
        outcome = service.run(
            context=context("user-a", include_role=False),
            task_text="Missing context must fail closed.",
            query="boundarytoken",
        )
    finally:
        provider.close()

    assert outcome.status is RunStatus.PERMISSION_STOPPED
    assert outcome.permission_result is not None
    assert outcome.permission_result.state is PermissionState.UNKNOWN
    assert retrieval.calls == []
    assert model.requests == []
    persisted = store.get(outcome.run_id)
    assert persisted is not None
    assert persisted.retrieval_called is False
    assert persisted.model_called is False
