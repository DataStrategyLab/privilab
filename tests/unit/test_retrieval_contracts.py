from __future__ import annotations

import inspect

import pytest

from privilab.application import (
    PermissionPolicy,
    RetrievalProvider,
    access_scope_for,
    parse_permission_policy,
)
from privilab.domain import (
    AccessScope,
    ChunkId,
    ClientContext,
    MatterContext,
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


def full_context() -> SyntheticRequestContext:
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
) -> PermissionPolicy:
    return parse_permission_policy(
        {
            "schema_version": 1,
            "policy_id": "retrieval-policy",
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
                    "rule_id": "retrieval-rule",
                    "effect": effect,
                    "match": match
                    if match is not None
                    else {
                        "user_id": "user-a",
                        "role_id": "role-a",
                        "client_id": "client-a",
                        "matter_id": "matter-a",
                        "workflow_id": "workflow-a",
                    },
                    "condition_ids": condition_ids or [],
                }
            ],
        }
    )


def test_access_scope_is_available_only_through_permission_gate() -> None:
    scope = access_scope_for(full_context(), policy_for())

    assert scope is not None
    assert (scope.user_id, scope.role_id, scope.client_id) == (
        "user-a",
        "role-a",
        "client-a",
    )
    with pytest.raises(TypeError, match="created by access_scope_for"):
        AccessScope("user-a", "role-a", "client-a", "matter-a", "workflow-a")


@pytest.mark.parametrize(
    "policy",
    [
        policy_for("BLOCK"),
        policy_for("ALLOW", match={"user_id": "other-user"}),
        policy_for("ALLOW", condition_ids=["review-required"]),
    ],
)
def test_only_effective_allow_mints_access_scope(policy: PermissionPolicy) -> None:
    assert access_scope_for(full_context(), policy) is None


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
    assert access_scope_for(context, policy_for()) is None


def test_scope_factory_evaluates_the_supplied_context_not_a_cached_result() -> None:
    policy = parse_permission_policy(
        {
            "schema_version": 1,
            "policy_id": "context-bound-policy",
            "policy_version": "1.0.0",
            "synthetic": True,
            "required_context": ["user_id"],
            "rules": [
                {
                    "rule_id": "block-user-b",
                    "effect": "BLOCK",
                    "match": {"user_id": "user-b"},
                    "condition_ids": [],
                },
                {
                    "rule_id": "allow-user-a",
                    "effect": "ALLOW",
                    "match": {"user_id": "user-a"},
                    "condition_ids": [],
                },
            ],
        }
    )

    assert access_scope_for(full_context(), policy) is not None
    assert (
        access_scope_for(
            SyntheticRequestContext(
                user=UserContext(UserIdentity("user-b"), Role("role-a")),
                client=ClientContext("client-a"),
                matter=MatterContext("matter-a"),
                workflow=WorkflowContext("workflow-a"),
            ),
            policy,
        )
        is None
    )


@pytest.mark.parametrize("value", ["", " source-a", "source-a ", 1])
def test_stable_identifiers_reject_invalid_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        SourceId(value)  # type: ignore[arg-type]
    with pytest.raises((TypeError, ValueError)):
        ChunkId(value)  # type: ignore[arg-type]


def test_retrieval_identifiers_and_text_reject_lone_surrogates() -> None:
    source_id = SourceId("source-a")
    with pytest.raises(ValueError, match="UTF-8"):
        SourceId("\ud800")
    with pytest.raises(ValueError, match="UTF-8"):
        RetrievalChunk(ChunkId("chunk-a"), source_id, 0, "synthetic\ud800text")


@pytest.mark.parametrize("ordinal", [-1, 2**63, True])
def test_retrieval_chunk_ordinal_must_fit_sqlite_integer(ordinal: int) -> None:
    with pytest.raises(ValueError, match="SQLite signed 64-bit"):
        RetrievalChunk(ChunkId("chunk-a"), SourceId("source-a"), ordinal, "synthetic")


def test_source_requires_exact_complete_entitlement_and_stable_chunks() -> None:
    source_id = SourceId("source-a")
    chunk = RetrievalChunk(ChunkId("chunk-a"), source_id, 0, "synthetic text")
    entitlement = SourceEntitlement(
        source_id, "user-a", "role-a", "client-a", "matter-a", "workflow-a"
    )

    source = RetrievalSource(
        source_id,
        "Synthetic source",
        (chunk,),
        (entitlement,),
        source_version="1.0.0",
    )

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
            source_version="1.0.0",
        )


def test_source_and_chunk_text_allow_surrounding_whitespace() -> None:
    source_id = SourceId("source-a")
    chunk = RetrievalChunk(
        ChunkId("chunk-a"), source_id, 0, "\n  synthetic text with padding  \t"
    )

    source = RetrievalSource(
        source_id,
        "  Synthetic source  ",
        (chunk,),
        source_version="1.0.0",
    )

    assert source.title == "  Synthetic source  "
    assert source.chunks[0].text == "\n  synthetic text with padding  \t"


@pytest.mark.parametrize("text", ["", " \t\n "])
def test_source_and_chunk_text_reject_only_whitespace(text: str) -> None:
    source_id = SourceId("source-a")
    with pytest.raises(ValueError, match="non-whitespace"):
        RetrievalChunk(ChunkId("chunk-a"), source_id, 0, text)
    with pytest.raises(ValueError, match="non-whitespace"):
        RetrievalSource(source_id, text, (), source_version="1.0.0")


def test_source_and_chunk_text_reject_nul_characters() -> None:
    source_id = SourceId("source-a")
    with pytest.raises(ValueError, match="NUL"):
        RetrievalChunk(ChunkId("chunk-a"), source_id, 0, "synthetic\x00text")
    with pytest.raises(ValueError, match="NUL"):
        RetrievalSource(
            source_id,
            "Synthetic\x00source",
            (),
            source_version="1.0.0",
        )


@pytest.mark.parametrize("source_version", ["", "  ", " version", "version "])
def test_source_version_must_be_a_stable_identifier(source_version: str) -> None:
    with pytest.raises(ValueError, match="source version"):
        RetrievalSource(
            SourceId("source-a"),
            "Synthetic source",
            (),
            source_version=source_version,
        )
    with pytest.raises(ValueError, match="source version"):
        RetrievedChunk(
            SourceId("source-a"),
            ChunkId("chunk-a"),
            0,
            "Synthetic source",
            "Synthetic text",
            source_version=source_version,
        )


def test_retrieval_provider_contract_requires_scope_and_keyword_limit() -> None:
    signature = inspect.signature(RetrievalProvider.retrieve)

    assert list(signature.parameters) == ["self", "query", "access_scope", "limit"]
    assert signature.parameters["limit"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.return_annotation == "tuple[RetrievedChunk, ...]"


def test_scope_factory_rejects_wrong_contract_types() -> None:
    with pytest.raises(TypeError, match="SyntheticRequestContext"):
        access_scope_for(None, policy_for())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="PermissionPolicy"):
        access_scope_for(full_context(), None)  # type: ignore[arg-type]
