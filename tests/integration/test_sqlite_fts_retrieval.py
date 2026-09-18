from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from privilab.adapters.models import FixtureModelProvider
from privilab.adapters.retrieval import SQLiteFtsRetrievalProvider
from privilab.adapters.retrieval import sqlite_fts as retrieval_sqlite
from privilab.adapters.retrieval.sqlite_fts import _SCHEMA
from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.application import (
    ModelRequest,
    RunService,
    access_scope_for,
    parse_permission_policy,
)
from privilab.domain import (
    AccessScope,
    ChunkId,
    ClientContext,
    MatterContext,
    ResearchResult,
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


def r06_physical_snapshot(database_path: Path) -> tuple[object, ...]:
    # Broken virtual tables may be unreadable; inspect all underlying rows instead.
    with closing(sqlite3.connect(database_path)) as connection:
        schema = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY type, name"
        ).fetchall()
        return schema, {
            name: sorted(
                connection.execute('SELECT * FROM "' + name + '"').fetchall(),
                key=repr,
            )
            for kind, name, _table, sql in schema
            if kind == "table" and not sql.upper().startswith("CREATE VIRTUAL")
        }


def assert_r06_retrieval_rejected_unchanged(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = r06_physical_snapshot(database_path)
    before_bytes = database_path.read_bytes()
    statements: list[str] = []
    connections: list[sqlite3.Connection] = []
    original = sqlite3.connect

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection: sqlite3.Connection = original(*args, **kwargs)
        if str(args[0]) == str(database_path):
            connection.set_trace_callback(statements.append)
            connections.append(connection)
        return connection

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", connect)
        with pytest.raises(RuntimeError, match=_INCOMPATIBLE_INDEX_ERROR):
            with closing(SQLiteFtsRetrievalProvider(database_path)):
                pass
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")
    assert not any(
        sql.lstrip()
        .upper()
        .startswith(("CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE"))
        for sql in statements
    )
    assert r06_physical_snapshot(database_path) == before
    assert database_path.read_bytes() == before_bytes


def test_post_r07_a_missing_populated_content_rejects_before_retrieval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "missing-content-row.sqlite3"
    with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
        retrieval.index_source(source("source", (("chunk", 0, "notice"),)))
        assert len(retrieval.retrieve("notice", scope_for())) == 1
    before_schema, before_rows = r06_physical_snapshot(database_path)
    with closing(sqlite3.connect(database_path)) as connection, connection:
        removed = connection.execute(
            "DELETE FROM chunks_fts_content WHERE c0 = 'chunk'"
        )
        assert removed.rowcount == 1
    schema, rows = r06_physical_snapshot(database_path)
    assert schema == before_schema
    assert isinstance(rows, dict) and isinstance(before_rows, dict)
    assert rows["chunks_fts_content"] == []
    assert {
        name: data for name, data in rows.items() if name != "chunks_fts_content"
    } == {
        name: data for name, data in before_rows.items() if name != "chunks_fts_content"
    }
    before_bytes = database_path.read_bytes()
    with pytest.raises(RuntimeError, match=_INCOMPATIBLE_INDEX_ERROR):
        with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
            with pytest.raises(sqlite3.DatabaseError, match="malformed|missing row"):
                retrieval.retrieve("notice", scope_for())
            print("Finding A baseline: constructor accepted; real MATCH was malformed")
    assert r06_physical_snapshot(database_path) == (schema, rows)
    assert database_path.read_bytes() == before_bytes
    assert_r06_retrieval_rejected_unchanged(database_path, monkeypatch)


@pytest.mark.parametrize(
    "text, query, expected",
    [
        (None, "notice", 0),
        ("notice", "notice", 2),
        ('A "notice" with FTS punctuation: * + - ( )', "notice", 2),
        ("Avis café — naïve", "cafe", 2),
        ("法令公告", '"法令公告"', 2),
        ("!!! 🧪 —", "notice", 0),
        ("notice " * 2000, "notice", 2),
    ],
    ids=["empty", "populated", "quotes", "unicode", "cjk", "no-tokens", "long"],
)
def test_post_r07_a_valid_content_reopens_without_writes(
    tmp_path: Path, text: str | None, query: str, expected: int
) -> None:
    database_path = tmp_path / "valid-content.sqlite3"
    with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
        if text is not None:
            retrieval.index_source(
                source("source", (("first", 0, text), ("second", 1, text)))
            )
        assert len(retrieval.retrieve(query, scope_for())) == expected
    before = r06_physical_snapshot(database_path)
    before_bytes = database_path.read_bytes()
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA query_only = ON")
        retrieval_sqlite._validate_schema_compatibility(connection)
    with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
        assert len(retrieval.retrieve(query, scope_for())) == expected
    assert r06_physical_snapshot(database_path) == before
    assert database_path.read_bytes() == before_bytes


@pytest.mark.parametrize(
    "mutation",
    [
        "DELETE FROM chunks_fts_content WHERE c0 = 'second'",
        "UPDATE chunks_fts_content SET c1 = 'different' WHERE c0 = 'second'",
        "INSERT INTO chunks_fts_content(c0, c1) VALUES ('second', 'notice')",
        "INSERT INTO chunks_fts_content(c0, c1) VALUES ('orphan', 'notice')",
    ],
    ids=["missing-later-row", "text-mismatch", "duplicate", "orphan"],
)
def test_post_r07_a_content_correlation_checks_all_governed_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    database_path = tmp_path / "content-correlation.sqlite3"
    with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
        retrieval.index_source(
            source("source", (("first", 0, "notice"), ("second", 1, "notice")))
        )
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute(mutation)
        # The old LIMIT 1 content read still succeeds in each case.
        assert connection.execute(
            "SELECT chunk_id, text FROM chunks_fts LIMIT 1"
        ).fetchone() == ("first", "notice")
    assert_r06_retrieval_rejected_unchanged(database_path, monkeypatch)


def test_r06_01_entitlement_trigger_cannot_reach_real_model_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "malicious-trigger.sqlite3"
    SQLiteFtsRetrievalProvider(database_path).close()
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.executescript(
            "CREATE TRIGGER clone_entitlement AFTER INSERT ON source_entitlements "
            "WHEN NEW.user_id = 'Alice' BEGIN "
            "INSERT INTO source_entitlements VALUES (NEW.source_id, 'alice', "
            "NEW.role_id, NEW.client_id, NEW.matter_id, NEW.workflow_id); END;"
        )
    before = r06_physical_snapshot(database_path)
    before_bytes = database_path.read_bytes()
    requests: list[ModelRequest] = []
    generate = FixtureModelProvider.generate

    def capture(self: FixtureModelProvider, request: ModelRequest) -> ResearchResult:
        requests.append(request)
        return generate(self, request)

    monkeypatch.setattr(FixtureModelProvider, "generate", capture)
    with pytest.raises(RuntimeError, match=_INCOMPATIBLE_INDEX_ERROR):
        with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
            retrieval.index_source(
                source(
                    "private",
                    (("private-chunk", 0, "notice Alice-only synthetic text"),),
                    entitlements=(
                        ("Alice", "role-a", "client-a", "matter-a", "workflow-a"),
                    ),
                )
            )
            with closing(SQLiteProvenanceStore(tmp_path / "runs.sqlite3")) as store:
                service = RunService.from_governed_fixture(
                    policy=parse_permission_policy(
                        {
                            "schema_version": 1,
                            "policy_id": "r06",
                            "policy_version": "1",
                            "synthetic": True,
                            "required_context": [],
                            "rules": [
                                {
                                    "rule_id": "allow",
                                    "effect": "ALLOW",
                                    "match": {},
                                    "condition_ids": [],
                                }
                            ],
                        }
                    ),
                    retrieval_provider=retrieval,
                    fixture_id="model-output.synthetic-happy-path.001",
                    provenance_store=store,
                    configuration_id="r06",
                    configuration_version="1",
                    retrieval_provider_id="sqlite-fts5",
                    retrieval_provider_version="1",
                )
                service.run(
                    context=context(user_id="alice"),
                    task_text="Synthetic task",
                    query="notice",
                )
                assert [chunk.source_id for chunk in requests[0].source_chunks] == [
                    "private"
                ]
                print("R06-01 baseline: Alice-only text reached alice ModelRequest")
    assert requests == []
    assert r06_physical_snapshot(database_path) == before
    assert database_path.read_bytes() == before_bytes
    assert_r06_retrieval_rejected_unchanged(database_path, monkeypatch)


def test_r06_05_replace_conflict_cannot_desynchronize_fts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "replace.sqlite3"
    create_constraint_variant_database(
        database_path, chunk_unique=", UNIQUE (source_id, ordinal) ON CONFLICT REPLACE"
    )
    with pytest.raises(RuntimeError, match=_INCOMPATIBLE_INDEX_ERROR):
        with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
            retrieval.index_source(source("private", (("original", 0, "notice"),)))
            assert len(retrieval.retrieve("notice", scope_for())) == 1
            with closing(sqlite3.connect(database_path)) as connection, connection:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA recursive_triggers=OFF")
                connection.execute(
                    "INSERT INTO chunks VALUES ('replacement', 'private', 0, 'changed')"
                )
                assert connection.execute("SELECT chunk_id FROM chunks").fetchall() == [
                    ("replacement",)
                ]
                assert connection.execute(
                    "SELECT chunk_id FROM chunks_fts"
                ).fetchall() == [("original",)]
            assert retrieval.retrieve("notice", scope_for()) == ()
            print(
                "R06-05 baseline: replacement chunk and stale FTS row; "
                "authorized result disappeared"
            )
    assert_r06_retrieval_rejected_unchanged(database_path, monkeypatch)


@pytest.mark.parametrize("shadow", ["idx", "content", "data"])
@pytest.mark.parametrize("mode", ["missing", "altered"])
def test_r06_06_damaged_fts_shadows_rejected_at_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shadow: str, mode: str
) -> None:
    database_path = tmp_path / "damaged.sqlite3"
    with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
        retrieval.index_source(source("source", (("chunk", 0, "notice"),)))
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute(f"DROP TABLE chunks_fts_{shadow}")
        if mode == "altered":
            connection.execute(f"CREATE TABLE chunks_fts_{shadow}(dummy TEXT)")
    assert_r06_retrieval_rejected_unchanged(database_path, monkeypatch)


@pytest.mark.parametrize("table", ["sources", "source_entitlements", "chunks"])
@pytest.mark.parametrize("mixed_case", [False, True])
def test_r06_01_all_ordinary_table_triggers_reject_before_ddl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, table: str, mixed_case: bool
) -> None:
    database_path = tmp_path / "trigger.sqlite3"
    SQLiteFtsRetrievalProvider(database_path).close()
    if mixed_case:
        table = table.title()
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute(
            f"CREATE TRIGGER surprise AFTER INSERT ON {table} BEGIN SELECT 1; END"
        )
    assert_r06_retrieval_rejected_unchanged(database_path, monkeypatch)


@pytest.mark.parametrize(
    "name",
    ["SoUrCeS", "source_entitlements", "chunks", "Chunks_Fts", "Chunks_Fts_Data"],
)
def test_r06_01_complete_schema_trigger_name_collision_on_unrelated_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    database_path = tmp_path / "collision.sqlite3"
    SQLiteFtsRetrievalProvider(database_path).close()
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")
        connection.execute(
            f"CREATE TRIGGER {name} AFTER INSERT ON unrelated BEGIN SELECT 1; END"
        )
    assert_r06_retrieval_rejected_unchanged(database_path, monkeypatch)


_R06_KEYS = (
    "source_id TEXT PRIMARY KEY",
    "chunk_id TEXT PRIMARY KEY",
    "UNIQUE (source_id, user_id, role_id, client_id, matter_id, workflow_id)",
    "UNIQUE (source_id, ordinal)",
)


@pytest.mark.parametrize("key", _R06_KEYS)
@pytest.mark.parametrize("action", ["REPLACE", "IGNORE", "FAIL", "ROLLBACK"])
def test_r06_05_incompatible_conflict_actions_rejected_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str, action: str
) -> None:
    database_path = tmp_path / "conflict.sqlite3"
    with closing(sqlite3.connect(database_path)) as connection:
        connection.executescript(_SCHEMA.replace(key, key + f" ON CONFLICT {action}"))
    assert_r06_retrieval_rejected_unchanged(database_path, monkeypatch)


@pytest.mark.parametrize("key", _R06_KEYS)
@pytest.mark.parametrize("action", ["", " ON CONFLICT ABORT"])
def test_r06_05_default_and_explicit_abort_conflict_semantics_remain_valid(
    tmp_path: Path, key: str, action: str
) -> None:
    database_path = tmp_path / "abort.sqlite3"
    with closing(sqlite3.connect(database_path)) as connection:
        connection.executescript(_SCHEMA.replace(key, key + action))
    with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
        retrieval.index_source(source("source", (("chunk", 0, "notice"),)))
    with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
        assert [
            chunk.chunk_id.value for chunk in retrieval.retrieve("notice", scope_for())
        ] == ["chunk"]


@pytest.mark.parametrize("populated", [False, True])
def test_r06_06_readiness_probes_are_read_only_and_valid_indexes_reopen(
    tmp_path: Path, populated: bool
) -> None:
    database_path = tmp_path / "ready.sqlite3"
    with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
        if populated:
            retrieval.index_source(source("source", (("chunk", 0, "notice"),)))
    before = r06_physical_snapshot(database_path)
    before_bytes = database_path.read_bytes()
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA query_only=ON")
        statements: list[str] = []
        connection.set_trace_callback(statements.append)
        retrieval_sqlite._validate_schema_compatibility(connection)
    assert any(
        "SELECT chunk_id, text FROM chunks_fts LIMIT 1" in sql for sql in statements
    )
    assert any("MATCH" in sql and "LIMIT 1" in sql for sql in statements)
    assert not any("LIMIT 0" in sql or "integrity-check" in sql for sql in statements)
    with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
        assert len(retrieval.retrieve("notice", scope_for())) == int(populated)
    assert r06_physical_snapshot(database_path) == before
    assert database_path.read_bytes() == before_bytes


@pytest.mark.parametrize("fail", [False, True])
def test_r06_reference_catalog_uses_only_trusted_sql_and_closes_connections(
    monkeypatch: pytest.MonkeyPatch, fail: bool
) -> None:
    original = sqlite3.connect
    references: list[sqlite3.Connection] = []

    class Reference(sqlite3.Connection):
        def executescript(self, sql_script: str, /) -> sqlite3.Cursor:
            assert sql_script == _SCHEMA
            if fail:
                raise sqlite3.DatabaseError("synthetic reference failure")
            return super().executescript(sql_script)

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        assert args == (":memory:",)
        connection: sqlite3.Connection = original(*args, **kwargs, factory=Reference)
        references.append(connection)
        return connection

    retrieval_sqlite._expected_schema.cache_clear()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(sqlite3, "connect", connect)
            if fail:
                with pytest.raises(
                    sqlite3.DatabaseError, match="synthetic reference failure"
                ):
                    retrieval_sqlite._expected_schema()
            else:
                catalog = retrieval_sqlite._expected_schema()
                assert retrieval_sqlite._expected_schema() is catalog
                assert len(catalog.objects) == 9
                assert all(kind == "table" for kind, _name, _table in catalog.objects)
                assert isinstance(catalog, tuple)
                assert all(
                    isinstance(structure, tuple)
                    for _name, structure in catalog.structures
                )
        assert len(references) == 1
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            references[0].execute("SELECT 1")
    finally:
        retrieval_sqlite._expected_schema.cache_clear()


@pytest.mark.parametrize(
    "task", ["   ", "invalid\ud800", 123], ids=["whitespace", "surrogate", "wrong-type"]
)
def test_r06_07_invalid_task_cannot_read_real_sources_or_write_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, task: Any
) -> None:
    with (
        closing(
            SQLiteFtsRetrievalProvider(tmp_path / "retrieval.sqlite3")
        ) as retrieval,
        closing(SQLiteProvenanceStore(tmp_path / "runs.sqlite3")) as store,
    ):
        retrieval.index_source(
            source("source", (("chunk", 0, "notice protected synthetic text"),))
        )
        retrieve = Mock(wraps=retrieval.retrieve)
        append = Mock(wraps=store.append)
        generate = Mock(side_effect=AssertionError("model must not execute"))
        monkeypatch.setattr(retrieval, "retrieve", retrieve)
        monkeypatch.setattr(store, "append", append)
        monkeypatch.setattr(FixtureModelProvider, "generate", generate)
        service = RunService.from_governed_fixture(
            policy=parse_permission_policy(
                {
                    "schema_version": 1,
                    "policy_id": "r06",
                    "policy_version": "1",
                    "synthetic": True,
                    "required_context": [],
                    "rules": [
                        {
                            "rule_id": "allow",
                            "effect": "ALLOW",
                            "match": {},
                            "condition_ids": [],
                        }
                    ],
                }
            ),
            retrieval_provider=retrieval,
            provenance_store=store,
            fixture_id="model-output.synthetic-happy-path.001",
            configuration_id="r06",
            configuration_version="1",
            retrieval_provider_id="sqlite-fts5",
            retrieval_provider_version="1",
        )
        with pytest.raises((TypeError, ValueError)) as expected:
            ModelRequest(task, ())
        with pytest.raises(type(expected.value), match=f"^{expected.value}$"):
            service.run(context=context(), task_text=task, query="notice")
        retrieve.assert_not_called()
        generate.assert_not_called()
        append.assert_not_called()
    with closing(sqlite3.connect(tmp_path / "runs.sqlite3")) as connection:
        for table in (
            "runs",
            "run_configurations",
            "run_permission_conditions",
            "run_sources",
            "run_chunks",
            "model_executions",
        ):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (
                0,
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
