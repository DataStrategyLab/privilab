from __future__ import annotations

import json
import sqlite3
import traceback
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


@pytest.mark.parametrize("partial", [False, True], ids=["full", "partial"])
def test_post_r09_navigation_corruption_rejects_at_constructor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, partial: bool
) -> None:
    database_path = tmp_path / "navigation.sqlite3"
    with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
        retrieval.index_source(
            source("source", (("quartz", 0, "quartz"), ("omega", 1, "omega " * 8000)))
        )
        assert [
            chunk.chunk_id.value for chunk in retrieval.retrieve("quartz", scope_for())
        ] == ["quartz"]
    with closing(sqlite3.connect(database_path)) as connection, connection:
        schema = connection.execute(
            "SELECT * FROM sqlite_schema ORDER BY name"
        ).fetchall()
        chunks = connection.execute("SELECT * FROM chunks").fetchall()
        visible = connection.execute("SELECT chunk_id, text FROM chunks_fts").fetchall()
        assert (
            connection.execute(
                "SELECT count(*) FROM chunks_fts_data WHERE length(block) > 1000"
            ).fetchone()[0]
            >= 2
        )
        navigation_count = connection.execute(
            "SELECT count(*) FROM chunks_fts_idx"
        ).fetchone()[0]
        assert navigation_count > 1
        connection.execute(
            "DELETE FROM chunks_fts_idx WHERE term != X''"
            if partial
            else "DELETE FROM chunks_fts_idx"
        )
        remaining = connection.execute(
            "SELECT count(*) FROM chunks_fts_idx"
        ).fetchone()[0]
        assert 0 < remaining < navigation_count if partial else remaining == 0
        assert (
            connection.execute("SELECT * FROM sqlite_schema ORDER BY name").fetchall()
            == schema
        )
        assert connection.execute("SELECT * FROM chunks").fetchall() == chunks
        assert (
            connection.execute("SELECT chunk_id, text FROM chunks_fts").fetchall()
            == visible
        )
        # Real ordinary MATCH is wrong before the readiness gate runs.
        assert (
            connection.execute(
                "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ?", ('"quartz"',)
            ).fetchall()
            == []
        )
    assert_r06_retrieval_rejected_unchanged(database_path, monkeypatch)
    # Construction necessarily precedes RunService composition. Test that public
    # boundary, without allowing retrieve() or run() to satisfy the raises block.
    generate = Mock(side_effect=AssertionError("model must not execute"))
    monkeypatch.setattr(FixtureModelProvider, "generate", generate)
    with closing(SQLiteProvenanceStore(tmp_path / "runs.sqlite3")) as store:
        append = Mock(wraps=store.append)
        monkeypatch.setattr(store, "append", append)
        with pytest.raises(RuntimeError, match=_INCOMPATIBLE_INDEX_ERROR):
            with closing(SQLiteFtsRetrievalProvider(database_path)):
                pytest.fail("corrupt provider must not become a RunService dependency")
        append.assert_not_called()
    generate.assert_not_called()
    with closing(sqlite3.connect(tmp_path / "runs.sqlite3")) as connection:
        assert connection.execute("SELECT count(*) FROM runs").fetchone() == (0,)


@pytest.mark.parametrize(
    "text, terms",
    [
        ("quartz", ("quartz",)),
        ("QuArTz QUARTZ quartz", ("quartz",)),
        ("café naïve", ("cafe", "naive")),
        ("法令公告", ("法令公告",)),
        ('alpha-beta "gamma"', ("alpha", "beta", "gamma")),
        ("!!! —", ()),
        ("omega " * 8000 + "quartz", ("omega", "quartz")),
    ],
    ids=[
        "ascii",
        "normalized",
        "diacritics",
        "cjk",
        "punctuation",
        "tokenless",
        "multipage",
    ],
)
def test_post_r09_real_vocabulary_roundtrip_and_healthy_reopen(
    tmp_path: Path, text: str, terms: tuple[str, ...]
) -> None:
    database_path = tmp_path / "healthy.sqlite3"
    SQLiteFtsRetrievalProvider(database_path).close()
    with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
        retrieval.index_source(source("first", (("a", 0, text), ("b", 1, text))))
        retrieval.index_source(source("second", (("c", 0, text),)))
    before = retrieval_database_snapshot(database_path)
    before_bytes = database_path.read_bytes()
    # Inspect actual normalized vocabulary on a physical clone, not source text.
    with (
        closing(sqlite3.connect(database_path)) as target,
        closing(sqlite3.connect(":memory:")) as clone,
    ):
        target.backup(clone)
        clone.execute(
            "CREATE VIRTUAL TABLE temp.vocab "
            "USING fts5vocab(main, 'chunks_fts', 'instance')"
        )
        expected = clone.execute(
            "SELECT term, doc FROM temp.vocab WHERE col = 'text' "
            "GROUP BY term, doc ORDER BY term, doc"
        ).fetchall()
        assert expected == [(term, doc) for term in terms for doc in (1, 2, 3)]
        for term in terms:
            assert clone.execute(
                "SELECT rowid FROM main.chunks_fts "
                "WHERE chunks_fts MATCH ? ORDER BY rowid",
                ('text : "' + term.replace('"', '""') + '"',),
            ).fetchall() == [(1,), (2,), (3,)]
    with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
        assert retrieval_database_snapshot(database_path) == before
        assert database_path.read_bytes() == before_bytes
        retrieval.index_source(source("later", (("later", 0, "subsequent"),)))
        assert [
            chunk.chunk_id.value
            for chunk in retrieval.retrieve("subsequent", scope_for())
        ] == ["later"]
        assert (
            retrieval.retrieve(
                "subsequent",
                scope_for(
                    user_id="user-b",
                    role_id="role-b",
                    client_id="client-b",
                    matter_id="matter-b",
                    workflow_id="workflow-b",
                ),
            )
            == ()
        )


@pytest.mark.parametrize("stage", ["create", "enumerate", "match"])
@pytest.mark.parametrize("kind", ["database", "memory"])
def test_post_r09_navigation_error_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str, kind: str
) -> None:
    database_path = tmp_path / "fault.sqlite3"
    with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
        retrieval.index_source(
            source("source", (("a", 0, "quartz omega"), ("b", 1, "quartz omega")))
        )
    before = retrieval_database_snapshot(database_path)
    before_bytes = database_path.read_bytes()
    original_connect = sqlite3.connect
    connections: list[sqlite3.Connection] = []
    injected = (
        MemoryError("private-term-marker")
        if kind == "memory"
        else sqlite3.DatabaseError("private-term-marker")
    )
    reached: list[str] = []

    class FaultCursor(sqlite3.Cursor):
        phase = ""
        reads = 0

        def __next__(self) -> Any:
            if self.phase == "enumerate" and stage == "enumerate":
                self.reads += 1
                if self.reads == 2:
                    reached.append(stage)
                    raise injected
            return super().__next__()

        def fetchone(self) -> Any:
            if self.phase == "match" and stage == "match":
                self.reads += 1
                if self.reads == 2:
                    reached.append(stage)
                    raise injected
            return super().fetchone()

    class Tracked(sqlite3.Connection):
        clone = False

        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            cursor = self.cursor(factory=FaultCursor)
            if self.clone:
                if (
                    "CREATE VIRTUAL TABLE temp._privilab_fts_validation_vocab" in sql
                    and stage == "create"
                ):
                    reached.append(stage)
                    raise injected
                if "FROM temp._privilab_fts_validation_vocab" in sql:
                    cursor.phase = "enumerate"
                if "FROM main.chunks_fts" in sql and "MATCH ?" in sql:
                    cursor.phase = "match"
            return cursor.execute(sql, parameters)

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = original_connect(*args, **kwargs, factory=Tracked)
        connection.clone = str(args[0]) == ":memory:"
        connections.append(connection)
        return connection

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", connect)
        if kind == "memory":
            with pytest.raises(MemoryError) as memory_error:
                SQLiteFtsRetrievalProvider(database_path)
            assert memory_error.value is injected
        else:
            with pytest.raises(
                RuntimeError, match=_INCOMPATIBLE_INDEX_ERROR
            ) as database_error:
                SQLiteFtsRetrievalProvider(database_path)
            assert "private-term-marker" not in "".join(
                traceback.format_exception(database_error.value)
            )
    assert reached == [stage]
    assert len(connections) == 2
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")
    assert retrieval_database_snapshot(database_path) == before
    assert database_path.read_bytes() == before_bytes


def test_post_r09_navigation_uses_only_existing_clone_after_native_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "clone-only.sqlite3"
    with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
        retrieval.index_source(
            source("source", (("a", 0, "quartz quartz"), ("b", 1, "quartz")))
        )
    original_connect = sqlite3.connect
    connections: list[sqlite3.Connection] = []
    commands: list[tuple[bool, str, Any]] = []

    class Tracked(sqlite3.Connection):
        clone = False

        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            commands.append((self.clone, sql, parameters))
            return super().execute(sql, parameters)

        def close(self) -> None:
            temp_objects = (
                super()
                .execute("SELECT name FROM sqlite_temp_schema WHERE type = 'table'")
                .fetchall()
            )
            persistent = (
                super()
                .execute(
                    "SELECT name FROM main.sqlite_schema "
                    "WHERE name = '_privilab_fts_validation_vocab'"
                )
                .fetchall()
            )
            super().close()
            assert temp_objects == (
                [("_privilab_fts_validation_vocab",)] if self.clone else []
            )
            assert persistent == []

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = original_connect(*args, **kwargs, factory=Tracked)
        connection.clone = str(args[0]) == ":memory:"
        connections.append(connection)
        return connection

    before_bytes = database_path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", connect)
        with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
            assert len(retrieval.retrieve("quartz", scope_for())) == 2
    assert len(connections) == 2
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")
    stages = []
    for clone, sql, parameters in commands:
        if "integrity-check" in sql:
            assert clone
            stages.append("native")
        if "CREATE VIRTUAL TABLE temp._privilab_fts_validation_vocab" in sql:
            assert clone and "fts5vocab(main, 'chunks_fts', 'instance')" in sql
            stages.append("vocab")
        if "FROM temp._privilab_fts_validation_vocab" in sql:
            assert clone and "WHERE col = 'text'" in sql
            assert "GROUP BY term, doc" in sql and "ORDER BY term, doc" in sql
            stages.append("expected")
        if "FROM main.chunks_fts" in sql and "MATCH ?" in sql:
            assert clone and parameters == ('text : "quartz"',)
            assert "ORDER BY rowid" in sql and "quartz" not in sql
            stages.append("actual")
    assert stages == ["native", "vocab", "expected", "actual"]
    assert database_path.read_bytes() == before_bytes


@pytest.mark.parametrize("mode", ["shifted-rowids", "missing-postings"])
def test_post_r08_postings_corruption_rejects_at_constructor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    database_path = tmp_path / "postings.sqlite3"
    with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
        retrieval.index_source(source("source", (("chunk", 0, "notice"),)))
        assert len(retrieval.retrieve("notice", scope_for())) == 1
    with closing(sqlite3.connect(database_path)) as connection, connection:
        schema = connection.execute(
            "SELECT * FROM sqlite_schema ORDER BY name"
        ).fetchall()
        chunks = connection.execute("SELECT * FROM chunks").fetchall()
        visible = connection.execute("SELECT chunk_id, text FROM chunks_fts").fetchall()
        if mode == "shifted-rowids":
            connection.execute("UPDATE chunks_fts_content SET id = id + 100")
        else:
            content = connection.execute("SELECT * FROM chunks_fts_content").fetchall()
            connection.execute("DELETE FROM chunks_fts")
            connection.executemany(
                "INSERT INTO chunks_fts_content VALUES (?, ?, ?)", content
            )
        assert (
            connection.execute("SELECT * FROM sqlite_schema ORDER BY name").fetchall()
            == schema
        )
        assert connection.execute("SELECT * FROM chunks").fetchall() == chunks
        assert (
            connection.execute("SELECT chunk_id, text FROM chunks_fts").fetchall()
            == visible
        )
    # The exception surrounds construction only; no trusted retrieval may begin.
    assert_r06_retrieval_rejected_unchanged(database_path, monkeypatch)


@pytest.mark.parametrize("existing", [False, True], ids=["fresh", "existing"])
@pytest.mark.parametrize(
    "failure",
    [
        "none",
        "transient-busy",
        "backup-error",
        "schema-error",
        "integrity-error",
        "busy",
        "locked",
        "deadline",
        "backup-memory",
        "schema-memory",
        "integrity-memory",
    ],
)
def test_post_r08_clone_gate_order_command_and_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing: bool,
    failure: str,
) -> None:
    database_path = tmp_path / "clone-boundary.sqlite3"
    if existing:
        with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
            retrieval.index_source(source("original", (("original", 0, "notice"),)))
    # Exclude the independently tested schema-reference connection from tracking.
    retrieval_sqlite._expected_schema()
    before_bytes = database_path.read_bytes() if existing else None
    original_connect = sqlite3.connect
    original_validate = retrieval_sqlite._validate_schema_compatibility
    targets: list[sqlite3.Connection] = []
    clones: list[sqlite3.Connection] = []
    events: list[str] = []
    target_sql: list[str] = []
    clone_sql: list[str] = []
    retries: list[int] = []

    class Tracked(sqlite3.Connection):
        role: str = ""

        def executescript(self, sql_script: str, /) -> sqlite3.Cursor:
            events.append(f"ddl-{self.role}")
            assert self.role == "target" and sql_script == _SCHEMA
            return super().executescript(sql_script)

        def backup(self, *args: Any, **kwargs: Any) -> None:
            events.append("backup")
            assert self.role == "target" and args[0] in clones
            assert kwargs["pages"] == 256 and kwargs["sleep"] == 0.01
            if failure == "backup-error":
                raise sqlite3.OperationalError("injected backup failure")
            if failure == "backup-memory":
                raise MemoryError("injected backup exhaustion")
            if failure in ("busy", "locked", "deadline"):
                status = {
                    "busy": sqlite3.SQLITE_BUSY,
                    "locked": sqlite3.SQLITE_LOCKED,
                    "deadline": sqlite3.SQLITE_OK,
                }[failure]
                for _ in range(10):
                    retries.append(status)
                    kwargs["progress"](status, 1, 2)
                pytest.fail("backup must stop within its internal bound")
            if failure == "transient-busy":
                for status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                    retries.append(status)
                    kwargs["progress"](status, 1, 2)
            super().backup(*args, **kwargs)

        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            if "integrity-check" in sql:
                events.append(f"integrity-{self.role}")
                assert self.role == "clone"
                if failure == "integrity-error":
                    raise sqlite3.DatabaseError("injected integrity failure")
                if failure == "integrity-memory":
                    raise MemoryError("injected integrity exhaustion")
            return super().execute(sql, parameters)

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        clone = str(args[0]) == ":memory:"
        assert clone or str(args[0]) == str(database_path)
        if clone:
            assert kwargs["timeout"] == 0
        connection = original_connect(*args, **kwargs, factory=Tracked)
        connection.role = "clone" if clone else "target"
        (clones if clone else targets).append(connection)
        connection.set_trace_callback((clone_sql if clone else target_sql).append)
        return connection

    def validate(connection: sqlite3.Connection) -> None:
        clone = connection in clones
        events.append("validate-clone" if clone else "validate-target")
        if clone and failure == "schema-error":
            raise sqlite3.OperationalError("injected clone compatibility failure")
        if clone and failure == "schema-memory":
            raise MemoryError("injected clone compatibility exhaustion")
        original_validate(connection)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", connect)
        patch.setattr(retrieval_sqlite, "_validate_schema_compatibility", validate)
        if failure == "deadline":
            patch.setattr(retrieval_sqlite, "monotonic", Mock(side_effect=[0.0, 5.0]))
        if failure in ("none", "transient-busy"):
            with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
                expected = (
                    [
                        "validate-target",
                        "backup",
                        "validate-clone",
                        "integrity-clone",
                        "ddl-target",
                        "validate-target",
                    ]
                    if existing
                    else [
                        "ddl-target",
                        "validate-target",
                        "backup",
                        "validate-clone",
                        "integrity-clone",
                    ]
                )
                assert events == expected
                if existing:
                    assert database_path.read_bytes() == before_bytes
                retrieval.index_source(source("new", (("new", 0, "notice"),)))
                assert len(retrieval.retrieve("notice", scope_for())) == 1 + int(
                    existing
                )
        elif failure.endswith("memory"):
            with pytest.raises(MemoryError, match="injected"):
                SQLiteFtsRetrievalProvider(database_path)
        else:
            with pytest.raises(RuntimeError, match=_INCOMPATIBLE_INDEX_ERROR):
                SQLiteFtsRetrievalProvider(database_path)
    assert len(clones) == len(targets) == events.count("backup") == 1
    for connection in [*clones, *targets]:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")
    assert not any("integrity-check" in sql for sql in target_sql)
    assert "ddl-clone" not in events
    if failure in ("none", "transient-busy"):
        assert sum("integrity-check" in sql for sql in clone_sql) == 1
    if failure in ("busy", "locked"):
        assert len(retries) == 5
    if failure == "deadline":
        assert len(retries) == 1
    if existing and failure not in ("none", "transient-busy"):
        assert "ddl-target" not in events
        assert database_path.read_bytes() == before_bytes


def test_post_r08_compatibility_validator_is_independent_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "read-only.sqlite3"
    with closing(SQLiteFtsRetrievalProvider(database_path)) as retrieval:
        retrieval.index_source(source("source", (("chunk", 0, "notice"),)))
    gate = Mock(side_effect=AssertionError("compatibility must not call clone gate"))
    monkeypatch.setattr(retrieval_sqlite, "_validate_fts_integrity", gate)
    before = database_path.read_bytes()
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA query_only = ON")
        retrieval_sqlite._validate_schema_compatibility(connection)
    gate.assert_not_called()
    assert database_path.read_bytes() == before


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
