from __future__ import annotations

import inspect

import pytest

from privilab.application import RetrievalProvider, access_scope_for
from privilab.domain import (
    AccessScope,
    ChunkId,
    ClientContext,
    ConditionId,
    MatterContext,
    PermissionResult,
    PermissionState,
    RetrievalChunk,
    RetrievalSource,
    Role,
    SourceEntitlement,
    SourceId,
    SyntheticRequestContext,
    UserContext,
    UserIdentity,
    WorkflowContext,
)


def full_context() -> SyntheticRequestContext:
    return SyntheticRequestContext(
        user=UserContext(UserIdentity("user-a"), Role("role-a")),
        client=ClientContext("client-a"),
        matter=MatterContext("matter-a"),
        workflow=WorkflowContext("workflow-a"),
    )


def test_access_scope_is_available_only_through_permission_gate() -> None:
    scope = access_scope_for(full_context(), PermissionResult(PermissionState.ALLOW))

    assert scope is not None
    assert (scope.user_id, scope.role_id, scope.client_id) == (
        "user-a",
        "role-a",
        "client-a",
    )
    with pytest.raises(TypeError, match="created by access_scope_for"):
        AccessScope("user-a", "role-a", "client-a", "matter-a", "workflow-a")


@pytest.mark.parametrize(
    "result",
    [
        PermissionResult(PermissionState.BLOCK),
        PermissionResult(PermissionState.UNKNOWN),
        PermissionResult(
            PermissionState.CONDITIONAL,
            frozenset({ConditionId("review-required")}),
        ),
    ],
)
def test_only_effective_allow_mints_access_scope(result: PermissionResult) -> None:
    assert access_scope_for(full_context(), result) is None


@pytest.mark.parametrize(
    "context",
    [
        SyntheticRequestContext(),
        SyntheticRequestContext(user=UserContext(UserIdentity("user-a"))),
        SyntheticRequestContext(
            user=UserContext(UserIdentity("user-a"), Role("role-a")),
            client=ClientContext("client-a"),
            matter=MatterContext("matter-a"),
        ),
    ],
)
def test_incomplete_context_cannot_mint_access_scope(
    context: SyntheticRequestContext,
) -> None:
    assert access_scope_for(context, PermissionResult(PermissionState.ALLOW)) is None


@pytest.mark.parametrize("value", ["", " source-a", "source-a ", 1])
def test_stable_identifiers_reject_invalid_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        SourceId(value)  # type: ignore[arg-type]
    with pytest.raises((TypeError, ValueError)):
        ChunkId(value)  # type: ignore[arg-type]


def test_source_requires_exact_complete_entitlement_and_stable_chunks() -> None:
    source_id = SourceId("source-a")
    chunk = RetrievalChunk(ChunkId("chunk-a"), source_id, 0, "synthetic text")
    entitlement = SourceEntitlement(
        source_id, "user-a", "role-a", "client-a", "matter-a", "workflow-a"
    )

    source = RetrievalSource(source_id, "Synthetic source", (chunk,), (entitlement,))

    assert source.chunks[0].chunk_id == ChunkId("chunk-a")
    with pytest.raises(ValueError, match="every entitlement must belong"):
        RetrievalSource(
            source_id,
            "Synthetic source",
            (chunk,),
            (
                SourceEntitlement(
                    SourceId("source-b"),
                    "user-a",
                    "role-a",
                    "client-a",
                    "matter-a",
                    "workflow-a",
                ),
            ),
        )


def test_retrieval_provider_contract_requires_scope_and_keyword_limit() -> None:
    signature = inspect.signature(RetrievalProvider.retrieve)

    assert list(signature.parameters) == ["self", "query", "access_scope", "limit"]
    assert signature.parameters["limit"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.return_annotation == "tuple[RetrievedChunk, ...]"


def test_scope_factory_rejects_wrong_contract_types() -> None:
    with pytest.raises(TypeError, match="SyntheticRequestContext"):
        access_scope_for(None, PermissionResult(PermissionState.ALLOW))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="PermissionResult"):
        access_scope_for(full_context(), None)  # type: ignore[arg-type]
