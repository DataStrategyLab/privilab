from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from privilab.adapters.retrieval import SQLiteFtsRetrievalProvider
from privilab.application import access_scope_for, parse_permission_policy
from privilab.domain import (
    AccessScope,
    ChunkId,
    ClientContext,
    MatterContext,
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

ROOT = Path(__file__).parents[2]


def context(
    *,
    user_id: str = "user-a",
    role_id: str = "role-a",
    client_id: str = "client-a",
    matter_id: str = "matter-a",
    workflow_id: str = "workflow-a",
) -> SyntheticRequestContext:
    return SyntheticRequestContext(
        user=UserContext(UserIdentity(user_id), Role(role_id)),
        client=ClientContext(client_id),
        matter=MatterContext(matter_id),
        workflow=WorkflowContext(workflow_id),
    )


ALLOW_POLICY = parse_permission_policy(
    {
        "schema_version": 1,
        "policy_id": "integration-retrieval-policy",
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
                "rule_id": "allow-context",
                "effect": "ALLOW",
                "match": {
                    "user_id": "user-a",
                    "role_id": "role-a",
                    "client_id": "client-a",
                    "matter_id": "matter-a",
                    "workflow_id": "workflow-a",
                },
                "condition_ids": [],
            },
            {
                "rule_id": "allow-second-context",
                "effect": "ALLOW",
                "match": {
                    "user_id": "user-b",
                    "role_id": "role-b",
                    "client_id": "client-b",
                    "matter_id": "matter-b",
                    "workflow_id": "workflow-b",
                },
                "condition_ids": [],
            },
        ],
    }
)


def scope_for(**kwargs: str) -> AccessScope:
    scope = access_scope_for(context(**kwargs), ALLOW_POLICY)
    assert scope is not None
    return scope


def source(
    source_id: str,
    chunks: tuple[tuple[str, int, str], ...],
    *,
    entitlements: tuple[tuple[str, str, str, str, str], ...] = (
        ("user-a", "role-a", "client-a", "matter-a", "workflow-a"),
    ),
) -> RetrievalSource:
    stable_source_id = SourceId(source_id)
    return RetrievalSource(
        stable_source_id,
        f"Synthetic {source_id}",
        tuple(
            RetrievalChunk(ChunkId(chunk_id), stable_source_id, ordinal, text)
            for chunk_id, ordinal, text in chunks
        ),
        tuple(
            SourceEntitlement(stable_source_id, *entitlement)
            for entitlement in entitlements
        ),
    )


@pytest.fixture
def provider(tmp_path: Path) -> Generator[SQLiteFtsRetrievalProvider]:
    instance = SQLiteFtsRetrievalProvider(tmp_path / "retrieval.sqlite3")
    yield instance
    instance.close()


def test_fts_returns_only_authorized_synthetic_corpus_chunk(
    provider: SQLiteFtsRetrievalProvider,
) -> None:
    payload = json.loads(
        (ROOT / "fixtures/corpus/synthetic_trade_notice_v1.json").read_text(
            encoding="utf-8"
        )
    )
    provider.index_source(
        source(
            payload["document_id"],
            (("synthetic-trade-notice-001.chunk-000", 0, payload["text"]),),
        )
    )
    provider.index_source(
        source(
            "source-unauthorized",
            (("source-unauthorized.chunk-000", 0, "notice confidential decoy"),),
            entitlements=(("user-b", "role-a", "client-a", "matter-a", "workflow-a"),),
        )
    )

    results = provider.retrieve("notice", scope_for())

    assert [(item.source_id.value, item.chunk_id.value) for item in results] == [
        ("synthetic-trade-notice-001", "synthetic-trade-notice-001.chunk-000")
    ]
    assert results[0].text == payload["text"]


def test_missing_entitlement_and_no_authorized_match_return_no_text(
    provider: SQLiteFtsRetrievalProvider,
) -> None:
    provider.index_source(
        source(
            "source-unknown-entitlement",
            (("source-unknown-entitlement.chunk-000", 0, "notice hidden"),),
            entitlements=(),
        )
    )

    assert provider.retrieve("notice", scope_for()) == ()


def test_source_supports_multiple_exact_entitlements(
    provider: SQLiteFtsRetrievalProvider,
) -> None:
    provider.index_source(
        source(
            "source-shared",
            (("source-shared.chunk-000", 0, "notice shared"),),
            entitlements=(
                ("user-a", "role-a", "client-a", "matter-a", "workflow-a"),
                ("user-b", "role-b", "client-b", "matter-b", "workflow-b"),
            ),
        )
    )

    assert provider.retrieve("notice", scope_for())[0].source_id == SourceId(
        "source-shared"
    )
    assert provider.retrieve(
        "notice",
        scope_for(
            user_id="user-b",
            role_id="role-b",
            client_id="client-b",
            matter_id="matter-b",
            workflow_id="workflow-b",
        ),
    )[0].source_id == SourceId("source-shared")


def test_ordering_limit_and_input_validation_are_deterministic(
    provider: SQLiteFtsRetrievalProvider,
) -> None:
    provider.index_source(
        source(
            "source-b",
            (
                ("source-b.chunk-001", 1, "notice"),
                ("source-b.chunk-000", 0, "notice"),
            ),
        )
    )
    provider.index_source(source("source-a", (("source-a.chunk-000", 0, "notice"),)))

    results = provider.retrieve("notice", scope_for(), limit=2)

    assert [(item.source_id.value, item.chunk_id.value) for item in results] == [
        ("source-a", "source-a.chunk-000"),
        ("source-b", "source-b.chunk-000"),
    ]
    for invalid_query in (
        "",
        " notice ",
        "notice\x00other",
        "\ud800",
        "bogus:hello",
        "*hello",
        None,
    ):
        with pytest.raises((TypeError, ValueError)):
            provider.retrieve(invalid_query, scope_for())  # type: ignore[arg-type]
    for invalid_limit in (0, 101, True):
        with pytest.raises(ValueError):
            provider.retrieve("notice", scope_for(), limit=invalid_limit)


def test_authorized_corpus_relevance_and_limit_ignore_other_scopes(
    provider: SQLiteFtsRetrievalProvider,
) -> None:
    provider.index_source(
        source(
            "source-a",
            (("source-a.chunk-000", 0, "notice confidential"),),
        )
    )
    provider.index_source(
        source(
            "source-b",
            (("source-b.chunk-000", 0, "notice notice confidential"),),
        )
    )

    before = provider.retrieve("notice confidential", scope_for(), limit=1)
    provider.index_source(
        source(
            "source-unauthorized",
            (("source-unauthorized.chunk-000", 0, "notice confidential"),),
            entitlements=(("user-b", "role-a", "client-a", "matter-a", "workflow-a"),),
        )
    )
    after = provider.retrieve("notice confidential", scope_for(), limit=1)

    assert [(item.source_id.value, item.chunk_id.value) for item in before] == [
        ("source-b", "source-b.chunk-000")
    ]
    assert after == before


def test_unicode_fts_matches_remain_retrievable_and_ranked(
    provider: SQLiteFtsRetrievalProvider,
) -> None:
    provider.index_source(
        source(
            "source-cafe",
            (("source-cafe.chunk-000", 0, "café café synthetic notice"),),
        )
    )
    provider.index_source(
        source(
            "source-cjk",
            (("source-cjk.chunk-000", 0, "合成 通知"),),
        )
    )

    cafe_results = provider.retrieve("cafe", scope_for())
    cjk_results = provider.retrieve("通知", scope_for())

    assert cafe_results[0].source_id == SourceId("source-cafe")
    assert cjk_results[0].source_id == SourceId("source-cjk")


def test_provider_supports_synchronous_worker_thread_calls(
    provider: SQLiteFtsRetrievalProvider,
) -> None:
    worker_source = source(
        "source-worker",
        (("source-worker.chunk-000", 0, "notice indexed by worker"),),
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(provider.index_source, worker_source).result()
        results = executor.submit(provider.retrieve, "notice", scope_for()).result()

    assert results[0].source_id == SourceId("source-worker")


def test_non_query_sqlite_operational_errors_remain_actionable(
    provider: SQLiteFtsRetrievalProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    class LockedConnection:
        def execute(self, *_args: object) -> None:
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(provider, "_connection", LockedConnection())

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        provider.retrieve("notice", scope_for())


def test_indexing_enforces_stable_foreign_key_and_uniqueness_constraints(
    provider: SQLiteFtsRetrievalProvider,
) -> None:
    provider.index_source(source("source-a", (("chunk-a", 0, "notice"),)))

    with pytest.raises(sqlite3.IntegrityError):
        provider.index_source(source("source-a", (("chunk-b", 0, "notice"),)))
    with pytest.raises(sqlite3.IntegrityError):
        provider.index_source(source("source-b", (("chunk-a", 0, "notice"),)))
