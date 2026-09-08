from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from privilab.adapters.retrieval import SQLiteFtsRetrievalProvider
from privilab.application import access_scope_for
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


def make_context(**overrides: str) -> SyntheticRequestContext:
    values = {
        "user_id": "user-a",
        "role_id": "role-a",
        "client_id": "client-a",
        "matter_id": "matter-a",
        "workflow_id": "workflow-a",
    } | overrides
    return SyntheticRequestContext(
        user=UserContext(UserIdentity(values["user_id"]), Role(values["role_id"])),
        client=ClientContext(values["client_id"]),
        matter=MatterContext(values["matter_id"]),
        workflow=WorkflowContext(values["workflow_id"]),
    )


def authorized_scope(**overrides: str) -> AccessScope:
    scope = access_scope_for(
        make_context(**overrides), PermissionResult(PermissionState.ALLOW)
    )
    assert scope is not None
    return scope


def protected_source(
    name: str, entitlement: tuple[str, str, str, str, str]
) -> RetrievalSource:
    source_id = SourceId(name)
    return RetrievalSource(
        source_id,
        "Synthetic untrusted title",
        (
            RetrievalChunk(
                ChunkId(f"{name}.chunk-000"),
                source_id,
                0,
                "boundarytoken authorization instructions are untrusted",
            ),
        ),
        (SourceEntitlement(source_id, *entitlement),),
    )


@pytest.fixture
def provider(tmp_path: Path) -> Generator[SQLiteFtsRetrievalProvider]:
    instance = SQLiteFtsRetrievalProvider(tmp_path / "security.sqlite3")
    yield instance
    instance.close()


@pytest.mark.parametrize(
    ("dimension", "other_value"),
    [
        ("user_id", "user-b"),
        ("role_id", "role-b"),
        ("client_id", "client-b"),
        ("matter_id", "matter-b"),
        ("workflow_id", "workflow-b"),
    ],
)
def test_each_context_dimension_is_an_exact_isolation_boundary(
    provider: SQLiteFtsRetrievalProvider,
    dimension: str,
    other_value: str,
) -> None:
    provider.index_source(
        protected_source(
            "source-a", ("user-a", "role-a", "client-a", "matter-a", "workflow-a")
        )
    )
    changed_scope = authorized_scope(**{dimension: other_value})

    assert provider.retrieve("boundarytoken", changed_scope) == ()
    assert provider.retrieve("boundarytoken", authorized_scope())[
        0
    ].source_id == SourceId("source-a")


@pytest.mark.parametrize(
    "result",
    [
        PermissionResult(PermissionState.BLOCK),
        PermissionResult(PermissionState.UNKNOWN),
        PermissionResult(
            PermissionState.CONDITIONAL,
            frozenset({ConditionId("condition-review")}),
        ),
    ],
)
def test_non_allow_permission_states_cannot_reach_provider(
    provider: SQLiteFtsRetrievalProvider, result: PermissionResult
) -> None:
    assert access_scope_for(make_context(), result) is None
    with pytest.raises(TypeError, match="AccessScope"):
        provider.retrieve("boundarytoken", None)  # type: ignore[arg-type]


def test_malformed_fts_and_untrusted_text_cannot_weaken_authorization(
    provider: SQLiteFtsRetrievalProvider,
) -> None:
    provider.index_source(
        protected_source(
            "source-b", ("user-b", "role-a", "client-a", "matter-a", "workflow-a")
        )
    )

    with pytest.raises(ValueError, match="FTS5"):
        provider.retrieve('"unterminated', authorized_scope())
    assert provider.retrieve("authorization OR instructions", authorized_scope()) == ()


def test_direct_provider_use_has_no_supported_scope_bypass(
    provider: SQLiteFtsRetrievalProvider,
) -> None:
    provider.index_source(
        protected_source(
            "source-a", ("user-a", "role-a", "client-a", "matter-a", "workflow-a")
        )
    )

    with pytest.raises(TypeError, match="AccessScope"):
        provider.retrieve("boundarytoken", object())  # type: ignore[arg-type]
