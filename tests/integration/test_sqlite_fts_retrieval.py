from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

from privilab.adapters.retrieval import SQLiteFtsRetrievalProvider
from privilab.adapters.retrieval.sqlite_fts import _SCHEMA
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
_INCOMPATIBLE_INDEX_ERROR = (
    "^local retrieval index schema is incompatible and must be recreated or rebuilt$"
)
_IDENTITY_DECLARATIONS = {
    "source_id": "source_id TEXT PRIMARY KEY",
    "entitlement_source": "source_id TEXT NOT NULL REFERENCES sources(source_id)",
    **{
        name: f"{name} TEXT NOT NULL"
        for name in ("user_id", "role_id", "client_id", "matter_id", "workflow_id")
    },
    "chunk_id": "chunk_id TEXT PRIMARY KEY",
    "chunk_source": "source_id TEXT NOT NULL REFERENCES sources(source_id)",
}


def create_constraint_variant_database(
    database_path: Path,
    **overrides: str,
) -> None:
    definitions = {
        **_IDENTITY_DECLARATIONS,
        "entitlement_unique": (
            ", UNIQUE (source_id, user_id, role_id, client_id, matter_id, workflow_id)"
        ),
        "ordinal": "ordinal INTEGER NOT NULL CHECK (ordinal >= 0)",
        "chunk_unique": ", UNIQUE (source_id, ordinal)",
        "fts": (
            "CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, text);"
        ),
    } | overrides
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.create_collation(
            "SYNTHETIC", lambda left, right: (left > right) - (left < right)
        )
        connection.executescript(
            f"""
            CREATE TABLE sources (
                {definitions["source_id"]},
                source_version TEXT NOT NULL,
                title TEXT NOT NULL
            );
            CREATE TABLE source_entitlements (
                {definitions["entitlement_source"]},
                {definitions["user_id"]},
                {definitions["role_id"]},
                {definitions["client_id"]},
                {definitions["matter_id"]},
                {definitions["workflow_id"]}
                {definitions["entitlement_unique"]}
            );
            CREATE TABLE chunks (
                {definitions["chunk_id"]},
                {definitions["chunk_source"]},
                {definitions["ordinal"]},
                text TEXT NOT NULL
                {definitions["chunk_unique"]}
            );
            {definitions["fts"]}
            """
        )
        connection.execute(
            """
            INSERT INTO sources (source_id, source_version, title)
            VALUES (?, ?, ?)
            """,
            ("existing-source", "1.0.0", "Existing synthetic source"),
        )


def retrieval_database_snapshot(database_path: Path) -> tuple[object, ...]:
    with closing(sqlite3.connect(database_path)) as connection:
        return (
            connection.execute(
                """
                SELECT type, name, tbl_name, sql
                FROM sqlite_schema
                ORDER BY type, name
                """
            ).fetchall(),
            {
                name: sorted(
                    connection.execute(
                        'SELECT * FROM "' + name.replace('"', '""') + '"'
                    ).fetchall(),
                    key=repr,
                )
                for (name,) in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type = 'table'"
                ).fetchall()
            },
        )


def test_hardening_rejects_nocase_column_with_binary_unique(tmp_path: Path) -> None:
    database_path = tmp_path / "nocase.sqlite3"
    create_constraint_variant_database(
        database_path,
        user_id="user_id TEXT NOT NULL COLLATE NOCASE",
        entitlement_unique=(
            ", UNIQUE (source_id, user_id COLLATE BINARY, role_id, "
            "client_id, matter_id, workflow_id)"
        ),
    )
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute(
            "INSERT INTO source_entitlements VALUES "
            "('existing-source', 'Alice', 'role-a', 'client-a', "
            "'matter-a', 'workflow-a')"
        )
        connection.execute(
            "INSERT INTO chunks VALUES ('chunk-a', 'existing-source', 0, 'notice')"
        )
        connection.execute("INSERT INTO chunks_fts VALUES ('chunk-a', 'notice')")
        # Demonstrate the dangerous comparison even though its UNIQUE is BINARY.
        assert connection.execute(
            "SELECT source_id FROM source_entitlements WHERE user_id = 'alice'"
        ).fetchall() == [("existing-source",)]
    before = retrieval_database_snapshot(database_path)
    before_bytes = database_path.read_bytes()
    with pytest.raises(RuntimeError, match=_INCOMPATIBLE_INDEX_ERROR):
        SQLiteFtsRetrievalProvider(database_path)
    assert retrieval_database_snapshot(database_path) == before
    assert database_path.read_bytes() == before_bytes


def test_hardening_partial_mixed_case_schema_is_untouched(tmp_path: Path) -> None:
    database_path = tmp_path / "partial.sqlite3"
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute("CREATE TABLE Chunks (chunk_id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO Chunks VALUES ('preserved-chunk')")
    before = retrieval_database_snapshot(database_path)
    before_bytes = database_path.read_bytes()
    with pytest.raises(RuntimeError, match=_INCOMPATIBLE_INDEX_ERROR):
        SQLiteFtsRetrievalProvider(database_path)
    assert retrieval_database_snapshot(database_path) == before
    assert database_path.read_bytes() == before_bytes


@pytest.mark.parametrize("column", _IDENTITY_DECLARATIONS)
@pytest.mark.parametrize(
    "collation",
    ["NOCASE", "RTRIM", "SYNTHETIC", "BINARY COLLATE BINARY", '"BINARY"'],
)
def test_hardening_rejects_nonbinary_or_ambiguous_identity_columns(
    tmp_path: Path, column: str, collation: str
) -> None:
    database_path = tmp_path / "identity-collation.sqlite3"
    create_constraint_variant_database(
        database_path,
        **{
            column: _IDENTITY_DECLARATIONS[column] + f" COLLATE {collation}",
            "entitlement_unique": (
                ", UNIQUE (source_id COLLATE BINARY, user_id COLLATE BINARY, "
                "role_id COLLATE BINARY, client_id COLLATE BINARY, "
                "matter_id COLLATE BINARY, workflow_id COLLATE BINARY)"
            ),
            "chunk_unique": ", UNIQUE (source_id COLLATE BINARY, ordinal)",
        },
    )
    before = retrieval_database_snapshot(database_path)
    before_bytes = database_path.read_bytes()
    with pytest.raises(RuntimeError, match=_INCOMPATIBLE_INDEX_ERROR):
        SQLiteFtsRetrievalProvider(database_path)
    assert retrieval_database_snapshot(database_path) == before
    assert database_path.read_bytes() == before_bytes


@pytest.mark.parametrize(
    "placement", ["default", "before-constraints", "after-constraints"]
)
def test_hardening_binary_columns_preserve_case_sensitive_isolation(
    tmp_path: Path, placement: str
) -> None:
    overrides = {}
    if placement != "default":
        overrides = {
            name: (
                clause.replace("TEXT", "TEXT COLLATE BINARY")
                if placement == "before-constraints"
                else clause + " COLLATE BINARY"
            )
            for name, clause in _IDENTITY_DECLARATIONS.items()
        }
    database_path = tmp_path / "binary.sqlite3"
    create_constraint_variant_database(database_path, **overrides)
    allow = parse_permission_policy(
        {
            "schema_version": 1,
            "policy_id": "synthetic-case-policy",
            "policy_version": "1",
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
                    "rule_id": "allow",
                    "effect": "ALLOW",
                    "match": {},
                    "condition_ids": [],
                }
            ],
        }
    )
    alice_context = dict(
        user_id="Alice",
        role_id="Role",
        client_id="Client",
        matter_id="Matter",
        workflow_id="Workflow",
    )
    instance = SQLiteFtsRetrievalProvider(database_path)
    try:
        for source_id, chunk_id, entitled in [
            ("Source", "Chunk", ("Alice", "Role", "Client", "Matter", "Workflow")),
            ("source", "chunk", ("Bob", "Role", "Client", "Matter", "Workflow")),
        ]:
            instance.index_source(
                source(source_id, ((chunk_id, 0, "notice"),), entitlements=(entitled,))
            )
    finally:
        instance.close()
    instance = SQLiteFtsRetrievalProvider(database_path)
    try:
        alice_scope = access_scope_for(context(**alice_context), allow)
        assert alice_scope is not None
        assert [
            chunk.chunk_id.value for chunk in instance.retrieve("notice", alice_scope)
        ] == ["Chunk"]
        for column in alice_context:
            variant = alice_context | {column: alice_context[column].lower()}
            variant_scope = access_scope_for(context(**variant), allow)
            assert variant_scope is not None
            assert instance.retrieve("notice", variant_scope) == ()
    finally:
        instance.close()


@pytest.mark.parametrize(
    "name",
    [
        "sources",
        "source_entitlements",
        "chunks",
        "chunks_fts",
        "chunks_fts_data",
        "chunks_fts_idx",
        "chunks_fts_content",
        "chunks_fts_docsize",
        "chunks_fts_config",
    ],
)
@pytest.mark.parametrize("mixed_case", [False, True])
@pytest.mark.parametrize("kind", ["table", "view", "index", "trigger"])
def test_hardening_partial_governed_objects_rejected_before_ddl(
    tmp_path: Path, name: str, mixed_case: bool, kind: str
) -> None:
    name = name.title() if mixed_case else name
    database_path = tmp_path / "partial-object.sqlite3"
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.execute("INSERT INTO unrelated VALUES ('preserve synthetic data')")
        if kind == "table":
            connection.execute(f"CREATE TABLE {name} (value TEXT PRIMARY KEY)")
            connection.execute(f"INSERT INTO {name} VALUES ('preserved')")
        elif kind == "view":
            connection.execute(f"CREATE VIEW {name} AS SELECT value FROM unrelated")
        elif kind == "index":
            connection.execute(f"CREATE INDEX {name} ON unrelated(value)")
        else:
            connection.execute(
                f"CREATE TRIGGER {name} AFTER INSERT ON unrelated BEGIN SELECT 1; END"
            )
    before = retrieval_database_snapshot(database_path)
    before_bytes = database_path.read_bytes()
    with pytest.raises(RuntimeError, match=_INCOMPATIBLE_INDEX_ERROR):
        SQLiteFtsRetrievalProvider(database_path)
    assert retrieval_database_snapshot(database_path) == before
    assert database_path.read_bytes() == before_bytes


@pytest.mark.parametrize(
    "missing", ["sources", "source_entitlements", "chunks", "chunks_fts"]
)
def test_hardening_incomplete_retrieval_combinations_are_untouched(
    tmp_path: Path, missing: str
) -> None:
    database_path = tmp_path / "incomplete.sqlite3"
    create_constraint_variant_database(database_path)
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute(f"DROP TABLE {missing}")
    before = retrieval_database_snapshot(database_path)
    before_bytes = database_path.read_bytes()
    with pytest.raises(RuntimeError, match=_INCOMPATIBLE_INDEX_ERROR):
        SQLiteFtsRetrievalProvider(database_path)
    assert retrieval_database_snapshot(database_path) == before
    assert database_path.read_bytes() == before_bytes


def test_hardening_complete_mixed_case_retrieval_schema_reopens(tmp_path: Path) -> None:
    database_path = tmp_path / "mixed-case.sqlite3"
    # Create the same governed definitions with ASCII case variants; quoted
    # ALTER TABLE rewrites are intentionally outside the bounded grammar.
    schema = _SCHEMA
    for name in ("sources", "source_entitlements", "chunks", "chunks_fts"):
        schema = schema.replace(f"EXISTS {name} ", f"EXISTS {name.title()} ")
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.executescript(schema)
    instance = SQLiteFtsRetrievalProvider(database_path)
    try:
        instance.index_source(source("source-a", (("chunk-a", 0, "notice"),)))
        assert len(instance.retrieve("notice", scope_for())) == 1
    finally:
        instance.close()


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
        source_version="1.0.0",
    )


@pytest.fixture
def provider(tmp_path: Path) -> Generator[SQLiteFtsRetrievalProvider]:
    instance = SQLiteFtsRetrievalProvider(tmp_path / "retrieval.sqlite3")
    yield instance
    instance.close()


def test_fresh_and_current_schema_support_source_version_after_reopen(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "current-retrieval.sqlite3"
    initial = SQLiteFtsRetrievalProvider(database_path)
    initial.index_source(
        source(
            "source-current",
            (("source-current.chunk-000", 0, "notice current schema"),),
        )
    )
    assert initial.retrieve("notice", scope_for())[0].source_version == "1.0.0"
    initial.close()

    reopened = SQLiteFtsRetrievalProvider(database_path)
    try:
        results = reopened.retrieve("notice", scope_for())
        assert len(results) == 1
        assert results[0].source_id == SourceId("source-current")
        assert results[0].source_version == "1.0.0"
    finally:
        reopened.close()


def test_legacy_schema_is_rejected_during_initialization_without_mutation(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-retrieval.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE sources (
                source_id TEXT PRIMARY KEY,
                title TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO sources (source_id, title) VALUES (?, ?)",
            ("legacy-source", "Legacy synthetic source"),
        )
        before_schema = connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_schema
            ORDER BY type, name
            """
        ).fetchall()
        before_rows = connection.execute(
            "SELECT source_id, title FROM sources ORDER BY source_id"
        ).fetchall()

    with pytest.raises(
        RuntimeError,
        match=(
            "^local retrieval index schema is incompatible and must be "
            "recreated or rebuilt$"
        ),
    ):
        SQLiteFtsRetrievalProvider(database_path)

    with sqlite3.connect(database_path) as connection:
        assert (
            connection.execute(
                """
            SELECT type, name, tbl_name, sql
            FROM sqlite_schema
            ORDER BY type, name
            """
            ).fetchall()
            == before_schema
        )
        assert (
            connection.execute(
                "SELECT source_id, title FROM sources ORDER BY source_id"
            ).fetchall()
            == before_rows
        )


def test_malformed_required_schema_is_rejected_deterministically(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "malformed-retrieval.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE sources (
                source_id TEXT PRIMARY KEY,
                source_version TEXT NOT NULL,
                title TEXT NOT NULL
            );
            CREATE TABLE source_entitlements (
                source_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role_id TEXT NOT NULL,
                client_id TEXT NOT NULL,
                matter_id TEXT NOT NULL,
                workflow_id TEXT NOT NULL
            );
            CREATE TABLE chunks (
                chunk_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL
            );
            CREATE VIRTUAL TABLE chunks_fts USING fts5(
                chunk_id UNINDEXED,
                text
            );
            """
        )

    with pytest.raises(
        RuntimeError,
        match=(
            "^local retrieval index schema is incompatible and must be "
            "recreated or rebuilt$"
        ),
    ):
        SQLiteFtsRetrievalProvider(database_path)


@pytest.mark.parametrize(
    "schema_overrides",
    (
        {"entitlement_source": "source_id TEXT NOT NULL"},
        {"chunk_source": "source_id TEXT NOT NULL"},
        {"chunk_source": ("source_id TEXT NOT NULL REFERENCES sources(title)")},
        {"entitlement_unique": ""},
        {
            "entitlement_unique": (
                ", UNIQUE (source_id, user_id, role_id, client_id, matter_id)"
            )
        },
        {"chunk_unique": ""},
        {"chunk_unique": ", UNIQUE (chunk_id, ordinal)"},
        {"ordinal": "ordinal INTEGER NOT NULL"},
        {"ordinal": "ordinal INTEGER NOT NULL CHECK (ordinal >= -1)"},
        {"fts": "CREATE TABLE chunks_fts (chunk_id, text);"},
        {"fts": "CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id, text);"},
        {
            "fts": (
                "CREATE VIRTUAL TABLE chunks_fts USING fts5("
                "chunk_id UNINDEXED, text UNINDEXED);"
            )
        },
    ),
    ids=(
        "missing-entitlement-foreign-key",
        "missing-chunk-foreign-key",
        "wrong-foreign-key-target-column",
        "missing-entitlement-unique",
        "incomplete-entitlement-unique",
        "missing-chunk-unique",
        "wrong-chunk-unique",
        "missing-ordinal-check",
        "weakened-ordinal-check",
        "ordinary-table-instead-of-fts5",
        "indexed-fts-chunk-id",
        "unindexed-fts-text",
    ),
)
def test_same_column_schema_with_incompatible_constraints_is_rejected_unchanged(
    tmp_path: Path,
    schema_overrides: dict[str, str],
) -> None:
    database_path = tmp_path / "incompatible-constraints.sqlite3"
    create_constraint_variant_database(database_path, **schema_overrides)
    before = retrieval_database_snapshot(database_path)

    with pytest.raises(RuntimeError, match=_INCOMPATIBLE_INDEX_ERROR):
        SQLiteFtsRetrievalProvider(database_path)

    assert retrieval_database_snapshot(database_path) == before


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
    assert results[0].source_version == "1.0.0"


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
        "foo : bar",
        "foo :bar",
        '"foo":bar',
        "{foo}:bar",
        "{foo text}:bar",
        "*hello",
        "NEAR(hello, x)",
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


def test_unicode_match_density_uses_character_length(
    provider: SQLiteFtsRetrievalProvider,
) -> None:
    provider.index_source(
        source(
            "source-a-one-match",
            (("source-a-one-match.chunk-000", 0, "cafe xxx"),),
        )
    )
    provider.index_source(
        source(
            "source-z-two-matches",
            (("source-z-two-matches.chunk-000", 0, "café café xxxx"),),
        )
    )

    results = provider.retrieve("cafe", scope_for(), limit=1)

    assert results[0].source_id == SourceId("source-z-two-matches")


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
