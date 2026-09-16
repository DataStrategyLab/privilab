from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from inspect import signature
from pathlib import Path
from typing import Any

import pytest

from privilab.adapters.models import FixtureModelProvider, load_governed_fixture
from privilab.adapters.models import governed_fixture as governed_fixture_loader
from privilab.adapters.retrieval import SQLiteFtsRetrievalProvider
from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.adapters.storage.sqlite_provenance import _TABLE_SCHEMA
from privilab.application import (
    ChunkProvenance,
    ContextProvenance,
    FailureStage,
    GovernedFixtureBinding,
    ModelRequest,
    PermissionPolicy,
    PermissionProvenance,
    PermissionStopReason,
    RunConfiguration,
    RunId,
    RunProvenance,
    RunService,
    RunStatus,
    SourceProvenance,
    governed_configuration_hash,
    parse_permission_policy,
)
from privilab.domain import (
    AccessScope,
    ChunkId,
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

ROOT = Path(__file__).parents[2]
GOVERNED_FIXTURES = ROOT / "src/privilab/adapters/models/resources/governed_fixtures"

_PROVENANCE_TABLES = (
    "runs",
    "run_configurations",
    "run_permission_conditions",
    "run_sources",
    "run_chunks",
    "model_executions",
)

_CHILD_RUN_ID_TRIGGERS = {
    "run_configurations": "prevent_run_configurations_run_id_update",
    "run_permission_conditions": ("prevent_run_permission_conditions_run_id_update"),
    "run_sources": "prevent_run_sources_run_id_update",
    "run_chunks": "prevent_run_chunks_run_id_update",
    "model_executions": "prevent_model_executions_run_id_update",
}


def synthetic_context() -> SyntheticRequestContext:
    return SyntheticRequestContext(
        user=UserContext(
            UserIdentity("synthetic-user-001"),
            Role("synthetic-researcher"),
        ),
        client=ClientContext("synthetic-client-001"),
        matter=MatterContext("synthetic-matter-001"),
        workflow=WorkflowContext("synthetic-workflow-001"),
    )


def policy(effect: str = "ALLOW") -> PermissionPolicy:
    return parse_permission_policy(
        {
            "schema_version": 1,
            "policy_id": "policy.synthetic-run.001",
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
                    "rule_id": "synthetic-run-rule",
                    "effect": effect,
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


def run_configuration(model_id: str, model_version: str) -> RunConfiguration:
    return RunConfiguration(
        configuration_id="p0-synthetic-run",
        configuration_version="1.0.0",
        provider_id="fixture-model-provider",
        provider_version="1",
        model_id=model_id,
        model_version=model_version,
        retrieval_provider_id="sqlite-fts5",
        retrieval_provider_version="1",
        retrieval_limit=10,
        options=(("result_contract", "research-result-v1"),),
    )


def provenance_source(
    source_id: str,
    *chunks: tuple[str, int, int],
) -> SourceProvenance:
    return SourceProvenance(
        source_id=source_id,
        source_version="1.0.0",
        chunks=tuple(
            ChunkProvenance(
                chunk_id=chunk_id,
                ordinal=ordinal,
                retrieval_position=retrieval_position,
            )
            for chunk_id, ordinal, retrieval_position in chunks
        ),
    )


def persisted_run(
    run_id: str,
    *,
    sources: tuple[SourceProvenance, ...] = (),
    unresolved_condition_id: str | None = None,
    failure_stage: FailureStage | None = None,
) -> RunProvenance:
    configuration = RunConfiguration(
        configuration_id=f"configuration-{run_id}",
        configuration_version="1.0.0",
        provider_id="fixture-model-provider",
        provider_version="1",
        model_id=f"fixture-{run_id}",
        model_version="1.0.0",
        retrieval_provider_id="sqlite-fts5",
        retrieval_provider_version="1",
        retrieval_limit=10,
    )
    timestamp = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    if unresolved_condition_id is not None:
        return RunProvenance(
            run_id=RunId(run_id),
            started_at=timestamp,
            completed_at=timestamp,
            status=RunStatus.PERMISSION_STOPPED,
            context=ContextProvenance.from_context(synthetic_context()),
            configuration=configuration,
            configuration_hash=f"sha256:{sha256(run_id.encode()).hexdigest()}",
            permission=PermissionProvenance(
                policy_id="policy.synthetic-run.001",
                policy_version="1.0.0",
                policy_schema_version=1,
                state=PermissionState.CONDITIONAL,
                unresolved_condition_ids=(unresolved_condition_id,),
            ),
            retrieval_called=False,
            model_called=False,
            stop_reason=PermissionStopReason.UNRESOLVED_CONDITIONS,
        )
    permission = (
        None
        if failure_stage is FailureStage.PERMISSION
        else PermissionProvenance(
            policy_id="policy.synthetic-run.001",
            policy_version="1.0.0",
            policy_schema_version=1,
            state=PermissionState.ALLOW,
        )
    )
    if failure_stage is not None:
        retrieval_called, model_called = {
            FailureStage.PERMISSION: (False, False),
            FailureStage.AUTHORIZATION: (False, False),
            FailureStage.RETRIEVAL: (True, False),
            FailureStage.MODEL: (True, True),
        }[failure_stage]
        return RunProvenance(
            run_id=RunId(run_id),
            started_at=timestamp,
            completed_at=timestamp,
            status=RunStatus.FAILED,
            context=ContextProvenance.from_context(synthetic_context()),
            configuration=configuration,
            configuration_hash=f"sha256:{sha256(run_id.encode()).hexdigest()}",
            permission=permission,
            retrieval_called=retrieval_called,
            model_called=model_called,
            failure_stage=failure_stage,
        )
    return RunProvenance(
        run_id=RunId(run_id),
        started_at=timestamp,
        completed_at=timestamp,
        status=RunStatus.GENERATED,
        context=ContextProvenance.from_context(synthetic_context()),
        configuration=configuration,
        configuration_hash=f"sha256:{sha256(run_id.encode()).hexdigest()}",
        permission=permission,
        retrieval_called=True,
        model_called=True,
        sources=sources,
    )


def child_run_id_move_case(
    table: str,
) -> tuple[
    RunProvenance,
    RunProvenance,
    str,
    str,
    tuple[str, tuple[str, ...]] | None,
]:
    source_run_id = f"{table}-source-run"
    destination_run_id = f"{table}-destination-run"
    if table == "run_configurations":
        return (
            persisted_run(source_run_id),
            persisted_run(destination_run_id),
            "configuration_id",
            f"configuration-{source_run_id}",
            (
                "DELETE FROM run_configurations WHERE run_id = ?",
                (destination_run_id,),
            ),
        )
    if table == "run_permission_conditions":
        return (
            persisted_run(
                source_run_id,
                unresolved_condition_id="condition-source",
            ),
            persisted_run(
                destination_run_id,
                unresolved_condition_id="condition-destination",
            ),
            "condition_id",
            "condition-source",
            None,
        )
    if table == "run_sources":
        return (
            persisted_run(
                source_run_id,
                sources=(
                    provenance_source(
                        "movable-source",
                        ("movable-source-chunk", 0, 0),
                    ),
                ),
            ),
            persisted_run(
                destination_run_id,
                sources=(
                    provenance_source(
                        "destination-source",
                        ("destination-source-chunk", 0, 0),
                    ),
                ),
            ),
            "source_id",
            "movable-source",
            (
                "DELETE FROM run_chunks WHERE run_id = ? AND source_id = ?",
                (source_run_id, "movable-source"),
            ),
        )
    if table == "run_chunks":
        return (
            persisted_run(
                source_run_id,
                sources=(
                    provenance_source(
                        "shared-source",
                        ("source-fixed-chunk", 0, 0),
                        ("movable-chunk", 1, 1),
                    ),
                ),
            ),
            persisted_run(
                destination_run_id,
                sources=(
                    provenance_source(
                        "shared-source",
                        ("destination-fixed-chunk", 0, 0),
                    ),
                ),
            ),
            "chunk_id",
            "movable-chunk",
            None,
        )
    if table == "model_executions":
        return (
            persisted_run(source_run_id),
            persisted_run(
                destination_run_id,
                failure_stage=FailureStage.RETRIEVAL,
            ),
            "model_id",
            f"fixture-{source_run_id}",
            None,
        )
    raise AssertionError(f"unsupported child table: {table}")


def provenance_database_snapshot(
    connection: sqlite3.Connection,
) -> dict[str, list[tuple[object, ...]]]:
    snapshot = {}
    for table in _PROVENANCE_TABLES:
        primary_key = [
            row[1]
            for row in sorted(
                connection.execute(f"PRAGMA table_info({table})"),
                key=lambda row: row[5],
            )
            if row[5]
        ]
        snapshot[table] = connection.execute(
            f"SELECT * FROM {table} ORDER BY {', '.join(primary_key)}"
        ).fetchall()
    return snapshot


def test_hardening_rowid_cannot_replace_finalized_last_chunk(tmp_path: Path) -> None:
    database_path = tmp_path / "rowid-attack.sqlite3"
    store = SQLiteProvenanceStore(database_path)
    record = persisted_run(
        "victim",
        sources=(provenance_source("source-a", ("first", 0, 0), ("last", 1, 1)),),
    )
    try:
        store.append(record)
        with sqlite3.connect(database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA recursive_triggers = OFF")
            insert_complete_raw_run(connection, "open-run")
            connection.execute(
                "INSERT INTO run_sources VALUES ('open-run', 'source-a', '1')"
            )
            before = provenance_database_snapshot(connection)
            # On the vulnerable layout, this takes the victim's hidden identity
            # but inserts under an open parent, bypassing the natural-key guard.
            with pytest.raises(sqlite3.OperationalError, match="rowid"):
                connection.execute(
                    "INSERT OR REPLACE INTO run_chunks "
                    "(rowid, run_id, source_id, chunk_id, ordinal, retrieval_position) "
                    "SELECT rowid, 'open-run', 'source-a', 'replacement', 0, 0 "
                    "FROM run_chunks WHERE run_id = 'victim' AND chunk_id = 'last'"
                )
            assert provenance_database_snapshot(connection) == before
        assert store.get(record.run_id) == record
    finally:
        store.close()


@pytest.mark.parametrize("table", _PROVENANCE_TABLES)
@pytest.mark.parametrize("alias", ["rowid", "_rowid_", "oid"])
def test_hardening_all_provenance_tables_have_no_rowid_alias(
    tmp_path: Path, table: str, alias: str
) -> None:
    database_path = tmp_path / "without-rowid.sqlite3"
    store = SQLiteProvenanceStore(database_path)
    record = (
        persisted_run("victim") if table == "runs" else child_run_id_move_case(table)[0]
    )
    try:
        store.append(record)
        with sqlite3.connect(database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA recursive_triggers = OFF")
            assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
            assert connection.execute("PRAGMA recursive_triggers").fetchone() == (0,)
            layouts = {
                row[1]: row[4]
                for row in connection.execute("PRAGMA table_list")
                if row[1] in _PROVENANCE_TABLES
            }
            assert layouts == dict.fromkeys(_PROVENANCE_TABLES, 1)
            before = provenance_database_snapshot(connection)
            for sql in (
                f"SELECT {alias} FROM {table}",
                f"UPDATE {table} SET {alias} = 999",
                f"INSERT OR REPLACE INTO {table} ({alias}) VALUES (1)",
            ):
                with pytest.raises(sqlite3.OperationalError, match=alias):
                    connection.execute(sql)
                assert provenance_database_snapshot(connection) == before
                assert store.get(record.run_id) == record
    finally:
        store.close()


@pytest.mark.parametrize("table", _PROVENANCE_TABLES)
def test_hardening_natural_key_replace_is_immutable_without_recursive_triggers(
    tmp_path: Path, table: str
) -> None:
    database_path = tmp_path / "natural-key.sqlite3"
    record = (
        persisted_run("victim") if table == "runs" else child_run_id_move_case(table)[0]
    )
    store = SQLiteProvenanceStore(database_path)
    try:
        store.append(record)
        with sqlite3.connect(database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA recursive_triggers = OFF")
            before = provenance_database_snapshot(connection)
            columns = [
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            ]
            projection = ", ".join(
                "0" if name == "is_finalized" else name for name in columns
            )
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) "
                    f"SELECT {projection} FROM {table} WHERE run_id = ?",
                    (record.run_id.value,),
                )
            assert provenance_database_snapshot(connection) == before
            assert store.get(record.run_id) == record
            if table == "run_chunks":
                with pytest.raises(sqlite3.IntegrityError):
                    connection.execute(
                        "INSERT OR REPLACE INTO run_chunks "
                        "SELECT run_id, source_id, 'new-natural-key', "
                        "ordinal, retrieval_position "
                        "FROM run_chunks WHERE run_id = ? AND retrieval_position = 1",
                        (record.run_id.value,),
                    )
                assert provenance_database_snapshot(connection) == before
                assert store.get(record.run_id) == record
    finally:
        store.close()


def complete_provenance_file_snapshot(database_path: Path) -> tuple[object, ...]:
    with closing(sqlite3.connect(database_path)) as connection:
        return (
            connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_schema "
                "ORDER BY type, name"
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


@pytest.mark.parametrize("table", _PROVENANCE_TABLES)
@pytest.mark.parametrize(
    "layout", ["partial-rowid", "partial-without-rowid", "mixed", "view"]
)
@pytest.mark.parametrize("mixed_case", [False, True])
def test_hardening_rejects_partial_or_mixed_provenance_before_ddl(
    tmp_path: Path, table: str, layout: str, mixed_case: bool
) -> None:
    statements = {
        statement.partition("(")[0].split()[-1]: statement
        for statement in _TABLE_SCHEMA.split(";")
        if statement.strip().startswith("CREATE TABLE")
    }
    actual_name = table.title() if mixed_case else table
    selected = statements[table].replace(f"EXISTS {table} (", f"EXISTS {actual_name} (")
    if layout in ("partial-rowid", "mixed"):
        selected = selected.replace(" WITHOUT ROWID", "")
    if layout == "view":
        selected = f"CREATE VIEW {actual_name} AS SELECT 'synthetic' AS run_id"
    schema = selected + ";"
    if layout == "mixed":
        schema = (
            ";".join(
                selected if name == table else sql for name, sql in statements.items()
            )
            + ";"
        )
    database_path = tmp_path / "incompatible-provenance.sqlite3"
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.executescript(schema)
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.execute("INSERT INTO unrelated VALUES ('preserve synthetic data')")
        if layout == "mixed":
            insert_complete_raw_run(connection, "preserved-open-run")
    before = complete_provenance_file_snapshot(database_path)
    before_bytes = database_path.read_bytes()
    with pytest.raises(RuntimeError, match="^local provenance schema is incompatible;"):
        SQLiteProvenanceStore(database_path)
    assert complete_provenance_file_snapshot(database_path) == before
    assert database_path.read_bytes() == before_bytes


@pytest.mark.parametrize(
    "variant", ["legacy-rowid", "missing-unique", "missing-primary-key-column"]
)
def test_hardening_rejects_incompatible_complete_provenance_without_mutation(
    tmp_path: Path, variant: str
) -> None:
    schema = _TABLE_SCHEMA
    if variant == "legacy-rowid":
        schema = schema.replace(" WITHOUT ROWID", "")
    elif variant == "missing-unique":
        schema = schema.replace("    UNIQUE (run_id, retrieval_position),", "")
    else:
        schema = schema.replace(
            "PRIMARY KEY (run_id, chunk_id)", "PRIMARY KEY (chunk_id)"
        )
    database_path = tmp_path / "legacy-provenance.sqlite3"
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.executescript(schema)
        insert_complete_raw_run(connection, "preserved-open-run")
    before = complete_provenance_file_snapshot(database_path)
    before_bytes = database_path.read_bytes()
    with pytest.raises(RuntimeError, match="^local provenance schema is incompatible;"):
        SQLiteProvenanceStore(database_path)
    assert complete_provenance_file_snapshot(database_path) == before
    assert database_path.read_bytes() == before_bytes


def test_hardening_without_rowid_append_duplicate_and_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "current-provenance.sqlite3"
    records = [
        persisted_run("generated"),
        persisted_run("conditional", unresolved_condition_id="needs-approval"),
        *(
            persisted_run(failure.value, failure_stage=failure)
            for failure in FailureStage
        ),
    ]
    store = SQLiteProvenanceStore(database_path)
    try:
        for record in records:
            store.append(record)
            assert store.get(record.run_id) == record
            with pytest.raises(sqlite3.IntegrityError):
                store.append(record)
            assert store.get(record.run_id) == record
    finally:
        store.close()
    before = complete_provenance_file_snapshot(database_path)
    store = SQLiteProvenanceStore(database_path)
    try:
        assert [store.get(record.run_id) for record in records] == records
    finally:
        store.close()
    assert complete_provenance_file_snapshot(database_path) == before


def test_hardening_valid_new_parent_text_reconstructs_after_finalization(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "new-valid-text.sqlite3"
    store = SQLiteProvenanceStore(database_path)
    try:
        with sqlite3.connect(database_path) as connection:
            insert_complete_raw_run(connection, "open-run")
            connection.execute(
                "UPDATE runs SET user_id = 'synthetic-new-user', "
                "role_id = 'synthetic-rôle', "
                "policy_id = 'new-policy', policy_version = '2', is_finalized = 1"
            )
        record = store.get(RunId("open-run"))
        assert record is not None
        assert record.context.user_id == "synthetic-new-user"
        assert record.context.role_id == "synthetic-rôle"
        assert record.permission is not None
        assert record.permission.policy_id == "new-policy"
        assert record.permission.policy_version == "2"
    finally:
        store.close()


@pytest.mark.parametrize(
    "column", ["user_id", "role_id", "policy_id", "policy_version"]
)
def test_hardening_finalization_validates_new_parent_text(
    tmp_path: Path, column: str
) -> None:
    database_path = tmp_path / "new-text.sqlite3"
    store = SQLiteProvenanceStore(database_path)
    try:
        with sqlite3.connect(database_path) as connection:
            insert_complete_raw_run(connection, "open-run")
            before = provenance_database_snapshot(connection)
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    f"UPDATE runs SET {column} = CAST(x'80' AS TEXT), is_finalized = 1 "
                    "WHERE run_id = 'open-run'"
                )
            assert provenance_database_snapshot(connection) == before
        assert store.get(RunId("open-run")) is None
    finally:
        store.close()


@pytest.mark.parametrize("column", ["started_at", "completed_at"])
@pytest.mark.parametrize("suffix", ["Z", "+00:00"])
@pytest.mark.parametrize("nul", ["trailing", "junk", "internal"])
@pytest.mark.parametrize("combined", [False, True])
def test_hardening_finalization_rejects_entire_nul_timestamp(
    tmp_path: Path, column: str, suffix: str, nul: str, combined: bool
) -> None:
    timestamp = "2026-09-14T12:00:00.000000" + suffix
    timestamp = (
        timestamp[:10] + "\x00" + timestamp[11:]
        if nul == "internal"
        else timestamp + ("\x00junk" if nul == "junk" else "\x00")
    )
    database_path = tmp_path / "nul-timestamp.sqlite3"
    store = SQLiteProvenanceStore(database_path)
    try:
        with sqlite3.connect(database_path) as connection:
            insert_complete_raw_run(connection, "open-run")
            if not combined:
                connection.execute(f"UPDATE runs SET {column} = ?", (timestamp,))
            before = provenance_database_snapshot(connection)
            with pytest.raises(sqlite3.IntegrityError):
                if combined:
                    connection.execute(
                        f"UPDATE runs SET {column} = ?, is_finalized = 1", (timestamp,)
                    )
                else:
                    connection.execute("UPDATE runs SET is_finalized = 1")
            assert provenance_database_snapshot(connection) == before
        assert store.get(RunId("open-run")) is None
    finally:
        store.close()


def insert_raw_run(
    connection: sqlite3.Connection,
    run_id: str,
    **overrides: Any,
) -> None:
    values: dict[str, Any] = {
        "run_id": run_id,
        "started_at": "2026-09-14T12:00:00.000000+00:00",
        "completed_at": "2026-09-14T12:00:00.000000+00:00",
        "status": "GENERATED",
        "stop_reason": None,
        "failure_stage": None,
        "synthetic_context": 1,
        "user_id": "synthetic-user-001",
        "role_id": "synthetic-researcher",
        "client_id": "synthetic-client-001",
        "matter_id": "synthetic-matter-001",
        "workflow_id": "synthetic-workflow-001",
        "policy_id": "policy.synthetic-run.001",
        "policy_version": "1.0.0",
        "policy_schema_version": 1,
        "permission_state": "ALLOW",
        "configuration_hash": f"sha256:{'0' * 64}",
        "retrieval_called": 1,
        "model_called": 1,
        "is_finalized": 0,
    }
    unexpected = set(overrides) - set(values)
    if unexpected:
        raise AssertionError(f"unknown raw run fields: {sorted(unexpected)}")
    values.update(overrides)
    columns = tuple(values)
    placeholders = ", ".join("?" for _column in columns)
    connection.execute(
        f"INSERT INTO runs ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(values[column] for column in columns),
    )


def insert_complete_raw_run(
    connection: sqlite3.Connection,
    run_id: str,
    *,
    run_overrides: dict[str, Any] | None = None,
    configuration_overrides: dict[str, Any] | None = None,
) -> None:
    """Insert a valid, complete OPEN run for finalization boundary probes."""
    insert_raw_run(connection, run_id, **(run_overrides or {}))
    configuration: dict[str, Any] = {
        "run_id": run_id,
        "configuration_id": "configuration-raw-run",
        "configuration_version": "1.0.0",
        "provider_id": "fixture-model-provider",
        "provider_version": "1",
        "model_id": "model-output.synthetic-raw.001",
        "model_version": "1.0.0",
        "model_content_hash": f"sha256:{'1' * 64}",
        "retrieval_provider_id": "sqlite-fts5",
        "retrieval_provider_version": "1",
        "retrieval_limit": 10,
        "options_json": '{"result_contract":"research-result-v1"}',
    }
    unexpected = set(configuration_overrides or {}) - set(configuration)
    if unexpected:
        raise AssertionError(f"unknown raw configuration fields: {unexpected}")
    configuration.update(configuration_overrides or {})
    columns = tuple(configuration)
    connection.execute(
        f"INSERT INTO run_configurations ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _column in columns)})",
        tuple(configuration[column] for column in columns),
    )
    if (run_overrides or {}).get("model_called", 1) == 1:
        connection.execute(
            """
            INSERT INTO model_executions (
                run_id, provider_id, provider_version, model_id,
                model_version, model_content_hash
            )
            SELECT run_id, provider_id, provider_version, model_id,
                   model_version, model_content_hash
            FROM run_configurations WHERE run_id = ?
            """,
            (run_id,),
        )


@pytest.mark.parametrize("table", tuple(_CHILD_RUN_ID_TRIGGERS))
def test_child_run_id_cannot_move_between_existing_runs(
    tmp_path: Path,
    table: str,
) -> None:
    source, destination, identity_column, identity_value, preparation = (
        child_run_id_move_case(table)
    )
    database_path = tmp_path / f"{table}.sqlite3"
    store = SQLiteProvenanceStore(database_path)
    try:
        store.append(source)
        store.append(destination)
        expected_source = store.get(source.run_id)
        expected_destination = store.get(destination.run_id)
    finally:
        store.close()

    trigger_name = _CHILD_RUN_ID_TRIGGERS[table]
    update_sql = (
        f"UPDATE {table} SET run_id = ? WHERE run_id = ? AND {identity_column} = ?"
    )
    update_parameters = (
        destination.run_id.value,
        source.run_id.value,
        identity_value,
    )
    preparation_trigger = {
        "run_configurations": "prevent_finalized_run_configurations_delete",
        "run_sources": "prevent_finalized_run_chunks_delete",
    }.get(table)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        before = provenance_database_snapshot(connection)
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
            (trigger_name,),
        ).fetchone()
        assert trigger is not None
        assert "BEFORE UPDATE OF run_id" in trigger[0]
        assert connection.execute(
            "SELECT count(*) FROM runs WHERE run_id = ?",
            (destination.run_id.value,),
        ).fetchone() == (1,)

        connection.execute("SAVEPOINT constraint_probe")
        if preparation_trigger is not None:
            connection.execute(f"DROP TRIGGER {preparation_trigger}")
        if preparation is not None:
            connection.execute(*preparation)
        connection.execute(f"DROP TRIGGER {trigger_name}")
        moved = connection.execute(update_sql, update_parameters)
        assert moved.rowcount == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            f"SELECT count(*) FROM {table} WHERE run_id = ? AND {identity_column} = ?",
            (source.run_id.value, identity_value),
        ).fetchone() == (0,)
        assert connection.execute(
            f"SELECT count(*) FROM {table} WHERE run_id = ? AND {identity_column} = ?",
            (destination.run_id.value, identity_value),
        ).fetchone() == (1,)
        connection.execute("ROLLBACK TO constraint_probe")
        connection.execute("RELEASE constraint_probe")

        connection.execute("SAVEPOINT protected_move")
        if preparation_trigger is not None:
            connection.execute(f"DROP TRIGGER {preparation_trigger}")
        if preparation is not None:
            connection.execute(*preparation)
        with pytest.raises(sqlite3.IntegrityError, match="run_id is immutable"):
            connection.execute(update_sql, update_parameters)
        connection.execute("ROLLBACK TO protected_move")
        connection.execute("RELEASE protected_move")

        assert provenance_database_snapshot(connection) == before
        assert connection.execute(
            f"SELECT count(*) FROM {table} WHERE run_id = ? AND {identity_column} = ?",
            (source.run_id.value, identity_value),
        ).fetchone() == (1,)
        assert connection.execute(
            f"SELECT count(*) FROM {table} WHERE run_id = ? AND {identity_column} = ?",
            (destination.run_id.value, identity_value),
        ).fetchone() == (0,)

    store = SQLiteProvenanceStore(database_path)
    try:
        assert store.get(source.run_id) == expected_source == source
        assert store.get(destination.run_id) == expected_destination == destination
    finally:
        store.close()


def finalized_child_insert(
    table: str,
    source_run_id: str,
) -> tuple[str, tuple[Any, ...], str | None]:
    if table == "run_configurations":
        return (
            """
            INSERT INTO run_configurations (
                run_id, configuration_id, configuration_version,
                provider_id, provider_version, model_id, model_version,
                model_content_hash, retrieval_provider_id,
                retrieval_provider_version, retrieval_limit, options_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_run_id,
                "replacement-configuration",
                "1.0.0",
                "fixture-model-provider",
                "1",
                "replacement-fixture",
                "1.0.0",
                None,
                "sqlite-fts5",
                "1",
                10,
                "{}",
            ),
            "prevent_finalized_run_configurations_delete",
        )
    if table == "run_permission_conditions":
        return (
            """
            INSERT INTO run_permission_conditions (run_id, condition_id)
            VALUES (?, ?)
            """,
            (source_run_id, "condition-new"),
            None,
        )
    if table == "run_sources":
        return (
            """
            INSERT INTO run_sources (run_id, source_id, source_version)
            VALUES (?, ?, ?)
            """,
            (source_run_id, "new-source", "1.0.0"),
            None,
        )
    if table == "run_chunks":
        return (
            """
            INSERT INTO run_chunks (
                run_id, source_id, chunk_id, ordinal, retrieval_position
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (source_run_id, "shared-source", "new-chunk", 2, 2),
            None,
        )
    if table == "model_executions":
        return (
            """
            INSERT INTO model_executions (
                run_id, provider_id, provider_version, model_id,
                model_version, model_content_hash
            )
            SELECT run_id, provider_id, provider_version, model_id,
                   model_version, model_content_hash
            FROM run_configurations WHERE run_id = ?
            """,
            (source_run_id,),
            "prevent_finalized_model_executions_delete",
        )
    raise AssertionError(f"unsupported child table: {table}")


@pytest.mark.parametrize("table", tuple(_CHILD_RUN_ID_TRIGGERS))
def test_finalized_child_provenance_rejects_every_mutation_form(
    tmp_path: Path,
    table: str,
) -> None:
    source, destination, identity_column, identity_value, _preparation = (
        child_run_id_move_case(table)
    )
    if table == "model_executions":
        destination = persisted_run(destination.run_id.value)
    database_path = tmp_path / f"finalized-{table}.sqlite3"
    store = SQLiteProvenanceStore(database_path)
    try:
        store.append(source)
        store.append(destination)
        expected_source = store.get(source.run_id)
        expected_destination = store.get(destination.run_id)
    finally:
        store.close()

    update_column = {
        "run_configurations": "configuration_version",
        "run_permission_conditions": "condition_id",
        "run_sources": "source_version",
        "run_chunks": "ordinal",
        "model_executions": "provider_version",
    }[table]
    insert_sql, insert_parameters, insert_delete_trigger = finalized_child_insert(
        table,
        source.run_id.value,
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA recursive_triggers = OFF")
        before = provenance_database_snapshot(connection)

        def assert_finalization_rejects(
            sql: str,
            parameters: tuple[Any, ...],
            *,
            prepare_insert_slot: bool = False,
        ) -> None:
            connection.execute("SAVEPOINT rejected_mutation")
            if prepare_insert_slot:
                assert insert_delete_trigger is not None
                connection.execute(f"DROP TRIGGER {insert_delete_trigger}")
                connection.execute(
                    f"DELETE FROM {table} WHERE run_id = ?",
                    (source.run_id.value,),
                )
                assert connection.execute(
                    f"SELECT count(*) FROM {table} WHERE run_id = ?",
                    (source.run_id.value,),
                ).fetchone() == (0,)
            with pytest.raises(
                sqlite3.IntegrityError,
                match="finalized run provenance is immutable",
            ):
                connection.execute(sql, parameters)
            connection.execute("ROLLBACK TO rejected_mutation")
            connection.execute("RELEASE rejected_mutation")
            assert provenance_database_snapshot(connection) == before

        assert_finalization_rejects(
            f"UPDATE {table} SET {update_column} = ? "
            f"WHERE run_id = ? AND {identity_column} = ?",
            ("99", source.run_id.value, identity_value),
        )
        assert_finalization_rejects(
            f"DELETE FROM {table} WHERE run_id = ? AND {identity_column} = ?",
            (source.run_id.value, identity_value),
        )
        assert_finalization_rejects(
            insert_sql,
            insert_parameters,
            prepare_insert_slot=insert_delete_trigger is not None,
        )
        table_columns = [
            row[1] for row in connection.execute(f"PRAGMA table_info({table})")
        ]
        replace_projection = ", ".join(
            "?" if column == "run_id" else column for column in table_columns
        )
        assert_finalization_rejects(
            f"INSERT OR REPLACE INTO {table} ({', '.join(table_columns)}) "
            f"SELECT {replace_projection} FROM {table} "
            f"WHERE run_id = ? AND {identity_column} = ?",
            (
                destination.run_id.value,
                source.run_id.value,
                identity_value,
            ),
        )

    store = SQLiteProvenanceStore(database_path)
    try:
        assert store.get(source.run_id) == expected_source == source
        assert store.get(destination.run_id) == expected_destination == destination
    finally:
        store.close()


def test_finalized_parent_cannot_reopen_mutate_delete_or_change_identity(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "finalized-parent.sqlite3"
    record = persisted_run("finalized-parent-run")
    store = SQLiteProvenanceStore(database_path)
    try:
        store.append(record)
        assert store.get(record.run_id) == record
    finally:
        store.close()

    with sqlite3.connect(database_path) as connection:
        before = provenance_database_snapshot(connection)
        assert connection.execute(
            "SELECT is_finalized FROM runs WHERE run_id = ?",
            (record.run_id.value,),
        ).fetchone() == (1,)
        for sql, parameters, message in (
            (
                "UPDATE runs SET is_finalized = 0 WHERE run_id = ?",
                (record.run_id.value,),
                "finalized run provenance is immutable",
            ),
            (
                "UPDATE runs SET completed_at = ? WHERE run_id = ?",
                ("2026-09-14T13:00:00+00:00", record.run_id.value),
                "finalized run provenance is immutable",
            ),
            (
                "DELETE FROM runs WHERE run_id = ?",
                (record.run_id.value,),
                "finalized run provenance is immutable",
            ),
            (
                "UPDATE runs SET run_id = ? WHERE run_id = ?",
                ("different-run-id", record.run_id.value),
                "run_id is immutable",
            ),
        ):
            with pytest.raises(sqlite3.IntegrityError, match=message):
                connection.execute(sql, parameters)
            assert provenance_database_snapshot(connection) == before
        run_columns = [row[1] for row in connection.execute("PRAGMA table_info(runs)")]
        replace_projection = ", ".join(
            "0" if column == "is_finalized" else column for column in run_columns
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="finalized run provenance is immutable",
        ):
            connection.execute(
                f"INSERT OR REPLACE INTO runs ({', '.join(run_columns)}) "
                f"SELECT {replace_projection} FROM runs WHERE run_id = ?",
                (record.run_id.value,),
            )
        assert provenance_database_snapshot(connection) == before


def test_failed_append_rolls_back_open_parent_and_all_child_provenance(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "failed-append.sqlite3"
    record = persisted_run(
        "partial-run",
        sources=(provenance_source("source-a", ("chunk-a", 0, 0)),),
    )
    store = SQLiteProvenanceStore(database_path)
    store.close()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_test_chunk_insert
            BEFORE INSERT ON run_chunks
            BEGIN
                SELECT RAISE(ABORT, 'synthetic child failure');
            END;
            """
        )

    store = SQLiteProvenanceStore(database_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="synthetic child failure"):
            store.append(record)
        assert store.get(record.run_id) is None
    finally:
        store.close()
    with sqlite3.connect(database_path) as connection:
        for table in _PROVENANCE_TABLES:
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (
                0,
            )


def test_open_or_incomplete_run_is_not_returned_as_persisted_provenance(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "open-run.sqlite3"
    store = SQLiteProvenanceStore(database_path)
    try:
        with sqlite3.connect(database_path) as connection:
            insert_raw_run(connection, "open-run")
        assert store.get(RunId("open-run")) is None
        with sqlite3.connect(database_path) as connection:
            with pytest.raises(
                sqlite3.IntegrityError,
                match="run provenance is incomplete",
            ):
                connection.execute(
                    "UPDATE runs SET is_finalized = 1 WHERE run_id = 'open-run'"
                )
    finally:
        store.close()


@pytest.mark.parametrize(
    "record",
    [
        persisted_run(
            "valid-permission-stopped",
            unresolved_condition_id="condition-review",
        ),
        persisted_run("valid-generated"),
        persisted_run(
            "valid-permission-failure", failure_stage=FailureStage.PERMISSION
        ),
        persisted_run(
            "valid-authorization-failure",
            failure_stage=FailureStage.AUTHORIZATION,
        ),
        persisted_run("valid-retrieval-failure", failure_stage=FailureStage.RETRIEVAL),
        persisted_run("valid-model-failure", failure_stage=FailureStage.MODEL),
    ],
    ids=lambda record: record.run_id.value,
)
def test_every_valid_terminal_call_state_finalizes_and_reconstructs(
    tmp_path: Path,
    record: RunProvenance,
) -> None:
    database_path = tmp_path / f"{record.run_id.value}.sqlite3"
    store = SQLiteProvenanceStore(database_path)
    try:
        store.append(record)
        assert store.get(record.run_id) == record
    finally:
        store.close()
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT is_finalized FROM runs WHERE run_id = ?",
            (record.run_id.value,),
        ).fetchone() == (1,)


@pytest.mark.parametrize(
    ("column", "invalid_value"),
    [
        ("configuration_hash", ""),
        ("configuration_hash", f"sha512:{'0' * 64}"),
        ("configuration_hash", f"sha256:{'0' * 63}"),
        ("configuration_hash", f"sha256:{'0' * 63}g"),
        ("configuration_hash", f"sha256:{'A' * 64}"),
        ("started_at", "not-a-timestamp"),
        ("started_at", "2026-09-14T12:00:00.000000"),
        ("started_at", "2026-02-30T12:00:00.000000+00:00"),
        ("started_at", "2026-09-14T12:60:00.000000+00:00"),
        ("started_at", "2026-09-14T12:00:00.000000+24:00"),
        ("started_at", "2026-09-14T12:00:00.000000+0A:00"),
        ("completed_at", "2026-09-14T12:00:60.000000+00:00"),
        ("completed_at", "2026-09-14T12:00:00.000000+00:60"),
        ("completed_at", "2026-09-13T23:59:59.999999+00:00"),
        ("completed_at", "2026-09-14T11:59:59.999999+00:00"),
        ("policy_schema_version", 1.5),
        ("user_id", ""),
        ("user_id", " synthetic-user-001"),
        ("user_id", sqlite3.Binary(b"synthetic-user-001")),
        ("role_id", "synthetic-researcher\N{NO-BREAK SPACE}"),
        ("policy_version", ""),
        ("policy_id", "policy.synthetic-run.001 "),
    ],
)
def test_finalization_rejects_invalid_raw_run_reconstruction_values(
    tmp_path: Path,
    column: str,
    invalid_value: Any,
) -> None:
    database_path = tmp_path / "invalid-raw-run-value.sqlite3"
    SQLiteProvenanceStore(database_path).close()
    run_id = "invalid-raw-run-value"
    with sqlite3.connect(database_path) as connection:
        insert_complete_raw_run(
            connection,
            run_id,
            run_overrides={column: invalid_value},
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="run provenance is incomplete",
        ):
            connection.execute(
                "UPDATE runs SET is_finalized = 1 WHERE run_id = ?",
                (run_id,),
            )
        assert connection.execute(
            "SELECT is_finalized FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone() == (0,)

    store = SQLiteProvenanceStore(database_path)
    try:
        assert store.get(RunId(run_id)) is None
    finally:
        store.close()


def test_finalization_compares_timestamp_order_at_microsecond_precision(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "invalid-microsecond-order.sqlite3"
    SQLiteProvenanceStore(database_path).close()
    run_id = "invalid-microsecond-order"
    with sqlite3.connect(database_path) as connection:
        insert_complete_raw_run(
            connection,
            run_id,
            run_overrides={
                "started_at": "2026-09-14T12:00:00.000999+00:00",
                "completed_at": "2026-09-14T12:00:00.000001+00:00",
            },
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE runs SET is_finalized = 1 WHERE run_id = ?",
                (run_id,),
            )
        assert connection.execute(
            "SELECT is_finalized FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone() == (0,)

    store = SQLiteProvenanceStore(database_path)
    try:
        assert store.get(RunId(run_id)) is None
    finally:
        store.close()


@pytest.mark.parametrize(
    "run_overrides",
    [
        {
            "started_at": "2026-09-14T12:00:00.000000+00:00",
            "completed_at": "2026-09-14T12:00:00.000000+00:00",
        },
        {
            "started_at": "2026-09-14T12:00:00.000000+00:00",
            "completed_at": "2026-09-14T12:00:00.000001+00:00",
        },
        {
            "started_at": "2026-09-14T23:59:59.999999Z",
            "completed_at": "2026-09-15T00:00:00.000000Z",
        },
        {
            "started_at": "2024-02-29T23:59:59.999999Z",
            "completed_at": "2024-03-01T00:00:00.000000Z",
        },
        {
            "started_at": "2026-09-14T12:00:00.000000Z",
            "completed_at": "2026-09-14T13:00:00.000000+01:00",
        },
        {
            "started_at": "2026-09-14T07:00:00.000000-05:00",
            "completed_at": "2026-09-14T12:00:00.000000Z",
        },
    ],
    ids=(
        "equal",
        "one-microsecond-after",
        "date-boundary-one-microsecond-after",
        "leap-day-boundary-one-microsecond-after",
        "equivalent-z-and-positive-offset",
        "equivalent-negative-offset-and-z",
    ),
)
def test_exact_timestamp_order_accepts_valid_boundaries(
    tmp_path: Path,
    run_overrides: dict[str, str],
) -> None:
    database_path = tmp_path / "valid-timestamp-order.sqlite3"
    SQLiteProvenanceStore(database_path).close()
    run_id = "valid-timestamp-order"
    with sqlite3.connect(database_path) as connection:
        insert_complete_raw_run(
            connection,
            run_id,
            run_overrides=run_overrides,
        )
        finalized = connection.execute(
            "UPDATE runs SET is_finalized = 1 WHERE run_id = ?",
            (run_id,),
        )
        assert finalized.rowcount == 1

    store = SQLiteProvenanceStore(database_path)
    try:
        record = store.get(RunId(run_id))
        assert record is not None
        assert record.completed_at >= record.started_at
    finally:
        store.close()


@pytest.mark.parametrize(
    "calendar_date",
    ("2000-02-29", "2024-02-29", "2026-04-30", "2026-12-31"),
)
def test_finalization_accepts_valid_calendar_dates(
    tmp_path: Path,
    calendar_date: str,
) -> None:
    database_path = tmp_path / f"valid-calendar-{calendar_date}.sqlite3"
    SQLiteProvenanceStore(database_path).close()
    run_id = f"valid-calendar-{calendar_date}"
    timestamp = f"{calendar_date}T12:00:00.000000Z"
    with sqlite3.connect(database_path) as connection:
        insert_complete_raw_run(
            connection,
            run_id,
            run_overrides={
                "started_at": timestamp,
                "completed_at": timestamp,
            },
        )
        finalized = connection.execute(
            "UPDATE runs SET is_finalized = 1 WHERE run_id = ?",
            (run_id,),
        )
        assert finalized.rowcount == 1

    store = SQLiteProvenanceStore(database_path)
    try:
        record = store.get(RunId(run_id))
        assert record is not None
        assert record.started_at.date().isoformat() == calendar_date
        assert record.completed_at.date().isoformat() == calendar_date
    finally:
        store.close()


@pytest.mark.parametrize("column", ("started_at", "completed_at"))
@pytest.mark.parametrize(
    "calendar_date",
    (
        "1900-02-29",
        "2023-02-29",
        "2024-02-30",
        "2026-04-31",
        "2026-00-01",
        "2026-13-01",
        "2026-01-00",
        "2026-01-32",
    ),
)
def test_finalization_rejects_invalid_calendar_dates(
    tmp_path: Path,
    column: str,
    calendar_date: str,
) -> None:
    database_path = tmp_path / f"invalid-calendar-{column}-{calendar_date}.sqlite3"
    SQLiteProvenanceStore(database_path).close()
    run_id = f"invalid-calendar-{column}-{calendar_date}"
    run_overrides = {
        "started_at": "0001-01-01T00:00:00.000000Z",
        "completed_at": "9999-12-31T23:59:59.999999Z",
        column: f"{calendar_date}T12:00:00.000000Z",
    }
    with sqlite3.connect(database_path) as connection:
        insert_complete_raw_run(
            connection,
            run_id,
            run_overrides=run_overrides,
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="run provenance is incomplete",
        ):
            connection.execute(
                "UPDATE runs SET is_finalized = 1 WHERE run_id = ?",
                (run_id,),
            )
        assert connection.execute(
            "SELECT is_finalized FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone() == (0,)

    store = SQLiteProvenanceStore(database_path)
    try:
        assert store.get(RunId(run_id)) is None
    finally:
        store.close()


@pytest.mark.parametrize(
    "run_overrides",
    [
        {
            "started_at": "2026-09-14T24:00:00.000000+00:00",
            "completed_at": "2026-09-15T00:00:00.000000+00:00",
        },
        {
            "started_at": "2026-09-14T23:00:00.000000+00:00",
            "completed_at": "2026-09-14T24:00:00.000000+00:00",
        },
        {
            "started_at": "2026-09-14T25:00:00.000000+00:00",
            "completed_at": "2026-09-15T02:00:00.000000+00:00",
        },
    ],
    ids=("started-hour-24", "completed-hour-24", "started-hour-25"),
)
def test_finalization_rejects_non_python_isoformat_hours(
    tmp_path: Path,
    run_overrides: dict[str, str],
) -> None:
    database_path = tmp_path / "invalid-hour.sqlite3"
    SQLiteProvenanceStore(database_path).close()
    run_id = "invalid-hour"
    with sqlite3.connect(database_path) as connection:
        insert_complete_raw_run(
            connection,
            run_id,
            run_overrides=run_overrides,
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="run provenance is incomplete",
        ):
            connection.execute(
                "UPDATE runs SET is_finalized = 1 WHERE run_id = ?",
                (run_id,),
            )
        assert connection.execute(
            "SELECT is_finalized FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone() == (0,)

    store = SQLiteProvenanceStore(database_path)
    try:
        assert store.get(RunId(run_id)) is None
    finally:
        store.close()


def test_hour_23_finalizes_and_reconstructs(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "valid-hour-23.sqlite3"
    SQLiteProvenanceStore(database_path).close()
    run_id = "valid-hour-23"
    with sqlite3.connect(database_path) as connection:
        insert_complete_raw_run(
            connection,
            run_id,
            run_overrides={
                "started_at": "2026-09-14T23:00:00.000000+00:00",
                "completed_at": "2026-09-14T23:59:59.999999+00:00",
            },
        )
        finalized = connection.execute(
            "UPDATE runs SET is_finalized = 1 WHERE run_id = ?",
            (run_id,),
        )
        assert finalized.rowcount == 1
        assert connection.execute(
            "SELECT is_finalized FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone() == (1,)

    store = SQLiteProvenanceStore(database_path)
    try:
        record = store.get(RunId(run_id))
        assert record is not None
        assert record.started_at.hour == 23
        assert record.completed_at.hour == 23
    finally:
        store.close()


@pytest.mark.parametrize(
    ("column", "invalid_value"),
    [
        ("model_content_hash", ""),
        ("model_content_hash", f"sha512:{'1' * 64}"),
        ("model_content_hash", f"sha256:{'1' * 63}"),
        ("model_content_hash", f"sha256:{'1' * 63}z"),
        ("model_content_hash", f"sha256:{'A' * 64}"),
        ("configuration_id", ""),
        ("configuration_version", "1.0.0 "),
        ("provider_id", " fixture-model-provider"),
        ("provider_version", ""),
        ("model_id", ""),
        ("model_version", " 1.0.0"),
        ("retrieval_provider_id", ""),
        ("retrieval_provider_version", "1 "),
        ("retrieval_limit", 1.5),
        ("options_json", "not-json"),
        ("options_json", "[]"),
        ("options_json", '{"result_contract":1}'),
        ("options_json", '{"":"research-result-v1"}'),
        ("options_json", '{" result_contract":"research-result-v1"}'),
        ("options_json", '{"result_contract":""}'),
        ("options_json", '{"result_contract":"research-result-v1 "}'),
        ("options_json", r'{"result_contract":"\ud800"}'),
        ("options_json", r'{"\ud800":"research-result-v1"}'),
    ],
)
def test_finalization_rejects_invalid_raw_configuration_values(
    tmp_path: Path,
    column: str,
    invalid_value: Any,
) -> None:
    database_path = tmp_path / "invalid-raw-configuration.sqlite3"
    SQLiteProvenanceStore(database_path).close()
    run_id = "invalid-raw-configuration"
    with sqlite3.connect(database_path) as connection:
        insert_complete_raw_run(
            connection,
            run_id,
            configuration_overrides={column: invalid_value},
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="run provenance is incomplete",
        ):
            connection.execute(
                "UPDATE runs SET is_finalized = 1 WHERE run_id = ?",
                (run_id,),
            )
        assert connection.execute(
            "SELECT is_finalized FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone() == (0,)

    store = SQLiteProvenanceStore(database_path)
    try:
        assert store.get(RunId(run_id)) is None
    finally:
        store.close()


def test_valid_escaped_unicode_option_finalizes_and_reconstructs(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "valid-unicode-option.sqlite3"
    SQLiteProvenanceStore(database_path).close()
    run_id = "valid-unicode-option"
    with sqlite3.connect(database_path) as connection:
        insert_complete_raw_run(
            connection,
            run_id,
            configuration_overrides={
                "options_json": r'{"output_symbol":"\ud83d\ude00"}'
            },
        )
        finalized = connection.execute(
            "UPDATE runs SET is_finalized = 1 WHERE run_id = ?",
            (run_id,),
        )
        assert finalized.rowcount == 1

    store = SQLiteProvenanceStore(database_path)
    try:
        record = store.get(RunId(run_id))
        assert record is not None
        assert record.configuration.options == (("output_symbol", "😀"),)
    finally:
        store.close()


@pytest.mark.parametrize(
    "mutation_sql",
    [
        """
        UPDATE runs
        SET user_id = CAST(x'80' AS TEXT)
        WHERE run_id = ?
        """,
        """
        UPDATE run_configurations
        SET configuration_id = CAST(x'C080' AS TEXT)
        WHERE run_id = ?
        """,
        """
        UPDATE run_configurations
        SET options_json = CAST(x'7B2278223A2280227D' AS TEXT)
        WHERE run_id = ?
        """,
    ],
)
def test_finalization_rejects_malformed_utf8_text_storage(
    tmp_path: Path,
    mutation_sql: str,
) -> None:
    database_path = tmp_path / "invalid-utf8.sqlite3"
    SQLiteProvenanceStore(database_path).close()
    run_id = "invalid-utf8"
    with sqlite3.connect(database_path) as connection:
        insert_complete_raw_run(connection, run_id)
        connection.execute(mutation_sql, (run_id,))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE runs SET is_finalized = 1 WHERE run_id = ?",
                (run_id,),
            )
        assert connection.execute(
            "SELECT is_finalized FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone() == (0,)

    store = SQLiteProvenanceStore(database_path)
    try:
        assert store.get(RunId(run_id)) is None
    finally:
        store.close()


@pytest.mark.parametrize(
    "invalid_child_sql",
    [
        """
        INSERT INTO run_sources (run_id, source_id, source_version)
        VALUES (?, 'source-invalid', '')
        """,
        """
        INSERT INTO run_sources (run_id, source_id, source_version)
        VALUES (?, '', '1.0.0')
        """,
    ],
)
def test_finalization_rejects_invalid_raw_source_identifiers(
    tmp_path: Path,
    invalid_child_sql: str,
) -> None:
    database_path = tmp_path / "invalid-raw-source.sqlite3"
    SQLiteProvenanceStore(database_path).close()
    run_id = "invalid-raw-source"
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        insert_complete_raw_run(connection, run_id)
        connection.execute(invalid_child_sql, (run_id,))
        source_id = connection.execute(
            "SELECT source_id FROM run_sources WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO run_chunks (
                run_id, source_id, chunk_id, ordinal, retrieval_position
            ) VALUES (?, ?, 'chunk-valid', 0, 0)
            """,
            (run_id, source_id),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE runs SET is_finalized = 1 WHERE run_id = ?",
                (run_id,),
            )
        assert connection.execute(
            "SELECT is_finalized FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone() == (0,)

    store = SQLiteProvenanceStore(database_path)
    try:
        assert store.get(RunId(run_id)) is None
    finally:
        store.close()


@pytest.mark.parametrize(
    ("column", "invalid_value"),
    [
        ("chunk_id", ""),
        ("chunk_id", " chunk-invalid"),
        ("ordinal", 0.5),
        ("retrieval_position", 0.5),
    ],
)
def test_finalization_rejects_invalid_raw_chunk_values(
    tmp_path: Path,
    column: str,
    invalid_value: Any,
) -> None:
    database_path = tmp_path / "invalid-raw-chunk.sqlite3"
    SQLiteProvenanceStore(database_path).close()
    run_id = "invalid-raw-chunk"
    chunk: dict[str, Any] = {
        "run_id": run_id,
        "source_id": "source-valid",
        "chunk_id": "chunk-valid",
        "ordinal": 0,
        "retrieval_position": 0,
    }
    chunk[column] = invalid_value
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        insert_complete_raw_run(connection, run_id)
        connection.execute(
            """
            INSERT INTO run_sources (run_id, source_id, source_version)
            VALUES (?, 'source-valid', '1.0.0')
            """,
            (run_id,),
        )
        columns = tuple(chunk)
        connection.execute(
            f"INSERT INTO run_chunks ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _column in columns)})",
            tuple(chunk[item] for item in columns),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE runs SET is_finalized = 1 WHERE run_id = ?",
                (run_id,),
            )
        assert connection.execute(
            "SELECT is_finalized FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone() == (0,)

    store = SQLiteProvenanceStore(database_path)
    try:
        assert store.get(RunId(run_id)) is None
    finally:
        store.close()


def test_finalization_rejects_invalid_run_and_condition_identifiers(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "invalid-raw-identifiers.sqlite3"
    SQLiteProvenanceStore(database_path).close()
    with sqlite3.connect(database_path) as connection:
        insert_complete_raw_run(connection, "")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE runs SET is_finalized = 1 WHERE run_id = ''")
        assert connection.execute(
            "SELECT is_finalized FROM runs WHERE run_id = ''"
        ).fetchone() == (0,)

        conditional_run_id = "invalid-condition"
        insert_complete_raw_run(
            connection,
            conditional_run_id,
            run_overrides={
                "status": "PERMISSION_STOPPED",
                "stop_reason": "UNRESOLVED_CONDITIONS",
                "permission_state": "CONDITIONAL",
                "retrieval_called": 0,
                "model_called": 0,
            },
        )
        connection.execute(
            """
            INSERT INTO run_permission_conditions (run_id, condition_id)
            VALUES (?, ' ')
            """,
            (conditional_run_id,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE runs SET is_finalized = 1 WHERE run_id = ?",
                (conditional_run_id,),
            )
        assert connection.execute(
            "SELECT is_finalized FROM runs WHERE run_id = ?",
            (conditional_run_id,),
        ).fetchone() == (0,)

    store = SQLiteProvenanceStore(database_path)
    try:
        assert store.get(RunId(conditional_run_id)) is None
    finally:
        store.close()


def test_missing_required_configuration_hash_never_becomes_visible(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "missing-configuration-hash.sqlite3"
    SQLiteProvenanceStore(database_path).close()
    run_id = "missing-configuration-hash"
    with sqlite3.connect(database_path) as connection:
        insert_complete_raw_run(connection, run_id)
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
            connection.execute(
                "UPDATE runs SET configuration_hash = NULL WHERE run_id = ?",
                (run_id,),
            )
        assert connection.execute(
            "SELECT is_finalized FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone() == (0,)

    store = SQLiteProvenanceStore(database_path)
    try:
        assert store.get(RunId(run_id)) is None
    finally:
        store.close()


def test_finalization_rejects_orphan_chunk_even_without_connection_foreign_keys(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "orphan-chunk.sqlite3"
    SQLiteProvenanceStore(database_path).close()
    run_id = "orphan-chunk"
    with sqlite3.connect(database_path) as connection:
        insert_complete_raw_run(connection, run_id)
        connection.execute(
            """
            INSERT INTO run_chunks (
                run_id, source_id, chunk_id, ordinal, retrieval_position
            ) VALUES (?, 'missing-source', 'orphan-chunk', 0, 0)
            """,
            (run_id,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE runs SET is_finalized = 1 WHERE run_id = ?",
                (run_id,),
            )
        assert connection.execute(
            "SELECT is_finalized FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone() == (0,)

    store = SQLiteProvenanceStore(database_path)
    try:
        assert store.get(RunId(run_id)) is None
    finally:
        store.close()


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "status": "PERMISSION_STOPPED",
            "stop_reason": "BLOCK",
            "permission_state": None,
            "policy_id": None,
            "policy_version": None,
            "policy_schema_version": None,
            "retrieval_called": 0,
            "model_called": 0,
        },
        {
            "status": "PERMISSION_STOPPED",
            "stop_reason": None,
            "permission_state": "BLOCK",
            "retrieval_called": 0,
            "model_called": 0,
        },
        {
            "status": "FAILED",
            "failure_stage": None,
            "retrieval_called": 0,
            "model_called": 0,
        },
        {"stop_reason": "BLOCK"},
        {"failure_stage": "MODEL"},
        {"retrieval_called": 0, "model_called": 1},
        {
            "status": "FAILED",
            "failure_stage": "RETRIEVAL",
            "permission_state": "UNKNOWN",
            "retrieval_called": 1,
            "model_called": 0,
        },
        {"policy_version": None},
        {
            "status": "FAILED",
            "failure_stage": "MODEL",
            "retrieval_called": 1,
            "model_called": 0,
        },
        {
            "status": "PERMISSION_STOPPED",
            "stop_reason": "BLOCK",
            "failure_stage": "PERMISSION",
            "permission_state": "BLOCK",
            "retrieval_called": 0,
            "model_called": 0,
        },
    ],
)
def test_raw_sql_rejects_invalid_terminal_or_policy_state(
    tmp_path: Path,
    overrides: dict[str, Any],
) -> None:
    database_path = tmp_path / "invalid-state.sqlite3"
    store = SQLiteProvenanceStore(database_path)
    store.close()
    with sqlite3.connect(database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            insert_raw_run(connection, "invalid-raw-run", **overrides)
        assert connection.execute("SELECT count(*) FROM runs").fetchone() == (0,)


def write_governed_fixture_tree(
    tmp_path: Path,
    *,
    content_hash: str | None = None,
    fixture_path: str = "output.json",
    fixture_id: str = "model-output.synthetic-bound.001",
    fixture_version: str = "1.0.0",
    answer_text: str = "Bound synthetic output.",
) -> tuple[Path, str, str]:
    resource_root = tmp_path / "governed-fixtures"
    resource_root.mkdir(parents=True)
    output_json = json.dumps(
        {"answer_text": answer_text, "citations": []},
        sort_keys=True,
    )
    output_path = resource_root / fixture_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_json, encoding="utf-8")
    actual_hash = f"sha256:{sha256(output_path.read_bytes()).hexdigest()}"
    manifest_path = resource_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "fixtures": [
                    {
                        "id": fixture_id,
                        "version": fixture_version,
                        "path": fixture_path,
                        "content_hash": content_hash or actual_hash,
                        "synthetic": True,
                        "license_ref": "fixture:synthetic-model-outputs",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return resource_root, output_json, actual_hash


def test_governed_fixture_loader_rejects_hash_mismatch_before_persistence(
    tmp_path: Path,
) -> None:
    repository_root, _output_json, _actual_hash = write_governed_fixture_tree(
        tmp_path,
        content_hash=f"sha256:{'0' * 64}",
    )
    database_path = tmp_path / "binding-failure.sqlite3"
    store = SQLiteProvenanceStore(database_path)
    store.close()

    with pytest.raises(ValueError, match="content hash does not match"):
        governed_fixture_loader._load_governed_fixture_for_testing(
            repository_root,
            "model-output.synthetic-bound.001",
        )

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT count(*) FROM runs").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM model_executions"
        ).fetchone() == (0,)


def test_governed_fixture_loader_rejects_unknown_identity_and_unsafe_path(
    tmp_path: Path,
) -> None:
    repository_root, _output_json, actual_hash = write_governed_fixture_tree(tmp_path)
    with pytest.raises(ValueError, match="identity is missing or duplicated"):
        load_governed_fixture("model-output.synthetic-missing.001")

    unsafe_root, _output_json, _unsafe_hash = write_governed_fixture_tree(
        tmp_path / "unsafe",
        content_hash=actual_hash,
        fixture_path="../outside.json",
    )
    with pytest.raises(ValueError, match="must not contain traversal"):
        governed_fixture_loader._load_governed_fixture_for_testing(
            unsafe_root,
            "model-output.synthetic-bound.001",
        )


def test_governed_fixture_loader_rejects_duplicate_manifest_identity(
    tmp_path: Path,
) -> None:
    resource_root, _output_json, _actual_hash = write_governed_fixture_tree(tmp_path)
    manifest_path = resource_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["fixtures"].append(dict(manifest["fixtures"][0]))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="identity is missing or duplicated"):
        governed_fixture_loader._load_governed_fixture_for_testing(
            resource_root,
            "model-output.synthetic-bound.001",
        )


@pytest.mark.parametrize(
    ("manifest_text", "message"),
    (
        ("{", "cannot load governed fixture manifest"),
        (
            '{"schema_version":"1","schema_version":"1","fixtures":[]}',
            "duplicate JSON field: schema_version",
        ),
    ),
)
def test_governed_fixture_loader_rejects_malformed_manifest(
    tmp_path: Path,
    manifest_text: str,
    message: str,
) -> None:
    resource_root, _output_json, _actual_hash = write_governed_fixture_tree(tmp_path)
    (resource_root / "manifest.json").write_text(manifest_text, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        governed_fixture_loader._load_governed_fixture_for_testing(
            resource_root,
            "model-output.synthetic-bound.001",
        )


def test_governed_fixture_loader_rejects_resolved_symlink_escape(
    tmp_path: Path,
) -> None:
    repository_root, _output_json, _actual_hash = write_governed_fixture_tree(
        tmp_path,
        fixture_path="linked-output.json",
    )
    linked_output = repository_root / "linked-output.json"
    outside_output = tmp_path / "outside-output.json"
    linked_output.replace(outside_output)
    linked_output.symlink_to(outside_output)

    with pytest.raises(ValueError, match="escapes its approved boundary"):
        governed_fixture_loader._load_governed_fixture_for_testing(
            repository_root,
            "model-output.synthetic-bound.001",
        )


def test_production_fixture_api_has_one_canonical_package_trust_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical_manifest = json.loads(
        (GOVERNED_FIXTURES / "manifest.json").read_text(encoding="utf-8")
    )
    canonical_record = canonical_manifest["fixtures"][0]
    fixture_id = canonical_record["id"]
    canonical_bytes = (GOVERNED_FIXTURES / canonical_record["path"]).read_bytes()
    canonical = load_governed_fixture(fixture_id)

    fake_root, fake_json, fake_hash = write_governed_fixture_tree(
        tmp_path,
        fixture_id=fixture_id,
        fixture_version=canonical_record["version"],
        answer_text="Fake same-identity output.",
    )
    test_only_fake = governed_fixture_loader._load_governed_fixture_for_testing(
        fake_root,
        fixture_id,
    )

    assert tuple(signature(load_governed_fixture).parameters) == ("fixture_id",)
    assert set(governed_fixture_loader.__all__) == {"load_governed_fixture"}
    assert canonical.model_id == fixture_id
    assert canonical.model_version == canonical_record["version"]
    assert canonical.content_hash == canonical_record["content_hash"]
    assert canonical.provider_id == "fixture-model-provider"
    assert canonical.provider_version == "1"
    assert isinstance(canonical.provider, FixtureModelProvider)
    assert canonical.provider.output_json.encode("utf-8") == canonical_bytes
    assert f"sha256:{sha256(canonical_bytes).hexdigest()}" == canonical.content_hash
    assert test_only_fake.content_hash == fake_hash
    assert isinstance(test_only_fake.provider, FixtureModelProvider)
    assert test_only_fake.provider.output_json == fake_json
    assert test_only_fake.provider.output_json.encode("utf-8") != canonical_bytes

    monkeypatch.chdir(fake_root)
    cwd_independent = load_governed_fixture(fixture_id)
    assert isinstance(cwd_independent.provider, FixtureModelProvider)
    assert cwd_independent.provider.output_json.encode("utf-8") == canonical_bytes

    production_loader: Any = load_governed_fixture
    with pytest.raises(TypeError):
        production_loader(
            fake_root,
            "alternate/manifest.json",
            fixture_id,
        )
    with pytest.raises(TypeError):
        production_loader(
            fixture_id,
            manifest_path="alternate/manifest.json",
        )

    composition_parameters = set(signature(RunService.from_governed_fixture).parameters)
    assert "fixture_id" in composition_parameters
    assert {
        "repository_root",
        "manifest_path",
        "fixture_bytes",
        "governed_fixture",
        "model_id",
        "model_version",
        "model_content_hash",
    }.isdisjoint(composition_parameters)


def test_stale_canonical_fixture_hash_fails_before_trusted_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = json.loads(
        (GOVERNED_FIXTURES / "manifest.json").read_text(encoding="utf-8")
    )
    canonical_record = manifest["fixtures"][0]
    canonical_payload = (GOVERNED_FIXTURES / canonical_record["path"]).resolve()
    original_read_bytes = Path.read_bytes

    def stale_canonical_bytes(path: Path) -> bytes:
        payload = original_read_bytes(path)
        return payload + b" " if path.resolve() == canonical_payload else payload

    monkeypatch.setattr(Path, "read_bytes", stale_canonical_bytes)
    database_path = tmp_path / "stale-canonical-binding.sqlite3"
    store = SQLiteProvenanceStore(database_path)
    try:
        with pytest.raises(ValueError, match="content hash does not match"):
            RunService.from_governed_fixture(
                policy=policy(),
                retrieval_provider=NeverRetrieval(),
                fixture_id=canonical_record["id"],
                provenance_store=store,
                configuration_id="p0-synthetic-run",
                configuration_version="1.0.0",
                retrieval_provider_id="sqlite-fts5",
                retrieval_provider_version="1",
            )
    finally:
        store.close()

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT count(*) FROM runs").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM model_executions"
        ).fetchone() == (0,)


def test_manual_fixture_payload_and_governed_identity_mismatch_is_not_constructible(
    tmp_path: Path,
) -> None:
    payload_a = json.dumps({"answer_text": "Payload A.", "citations": []})
    provider_a = FixtureModelProvider(payload_a)
    claimed_hash_b = f"sha256:{'b' * 64}"
    with pytest.raises(TypeError, match="must be created by load_governed_fixture"):
        GovernedFixtureBinding(
            provider=provider_a,
            model_id="model-output.synthetic-b.001",
            model_version="2.0.0",
            content_hash=claimed_hash_b,
            provider_id="fixture-model-provider",
            provider_version="1",
        )

    store = SQLiteProvenanceStore(tmp_path / "manual-mismatch.sqlite3")
    try:
        with pytest.raises(TypeError, match="RunService must be created"):
            RunService(
                policy=policy(),
                retrieval_provider=NeverRetrieval(),
                model_provider=provider_a,
                provenance_store=store,
                configuration=run_configuration(
                    "model-output.synthetic-b.001",
                    "2.0.0",
                ),
            )
        with pytest.raises(ValueError, match="from_governed_fixture"):
            RunService._from_components_for_testing(
                policy=policy(),
                retrieval_provider=NeverRetrieval(),
                model_provider=provider_a,
                provenance_store=store,
                configuration=replace(
                    run_configuration(
                        "model-output.synthetic-b.001",
                        "2.0.0",
                    ),
                    model_content_hash=claimed_hash_b,
                ),
            )
    finally:
        store.close()
    with sqlite3.connect(tmp_path / "manual-mismatch.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM runs").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM model_executions"
        ).fetchone() == (0,)


def test_end_to_end_allowed_run_persists_reconstructable_metadata_only(
    tmp_path: Path,
) -> None:
    corpus_manifest = json.loads(
        (ROOT / "fixtures/corpus/manifest.json").read_text(encoding="utf-8")
    )
    corpus_payload = json.loads(
        (ROOT / "fixtures/corpus/synthetic_trade_notice_v1.json").read_text(
            encoding="utf-8"
        )
    )
    model_manifest = json.loads(
        (GOVERNED_FIXTURES / "manifest.json").read_text(encoding="utf-8")
    )
    governed_source = next(
        record
        for record in corpus_manifest["records"]
        if record["id"] == "corpus.synthetic-trade-notice.001"
    )
    governed_model = next(
        record
        for record in model_manifest["fixtures"]
        if record["id"] == "model-output.synthetic-happy-path.001"
    )
    governed_fixture = load_governed_fixture(governed_model["id"])
    source_id = SourceId(governed_source["id"])
    chunk_id = ChunkId(f"{source_id.value}.chunk-000")
    retrieval_path = tmp_path / "retrieval.sqlite3"
    provenance_path = tmp_path / "provenance.sqlite3"
    retrieval = SQLiteFtsRetrievalProvider(retrieval_path)
    store = SQLiteProvenanceStore(provenance_path)
    try:
        retrieval.index_source(
            RetrievalSource(
                source_id=source_id,
                title=corpus_payload["title"],
                chunks=(
                    RetrievalChunk(
                        chunk_id=chunk_id,
                        source_id=source_id,
                        ordinal=0,
                        text=corpus_payload["text"],
                    ),
                ),
                entitlements=(
                    SourceEntitlement(
                        source_id,
                        "synthetic-user-001",
                        "synthetic-researcher",
                        "synthetic-client-001",
                        "synthetic-matter-001",
                        "synthetic-workflow-001",
                    ),
                ),
                source_version=governed_source["version"],
            )
        )
        fixture_bytes = (GOVERNED_FIXTURES / governed_model["path"]).read_bytes()
        assert (
            f"sha256:{sha256(fixture_bytes).hexdigest()}"
            == (governed_model["content_hash"])
        )
        fixture_payload = fixture_bytes.decode("utf-8")
        fixture_result = ResearchResult.from_json(fixture_payload)
        assert isinstance(governed_fixture.provider, FixtureModelProvider)
        assert governed_fixture.provider.output_json.encode("utf-8") == fixture_bytes
        service = RunService.from_governed_fixture(
            policy=policy(),
            retrieval_provider=retrieval,
            fixture_id=governed_model["id"],
            provenance_store=store,
            configuration_id="p0-synthetic-run",
            configuration_version="1.0.0",
            retrieval_provider_id="sqlite-fts5",
            retrieval_provider_version="1",
            retrieval_limit=10,
            options=(("result_contract", "research-result-v1"),),
        )
        task_text = "Summarize the governed synthetic notice."

        first = service.run(
            context=synthetic_context(),
            task_text=task_text,
            query="Synthetic",
        )
        first_record = store.get(first.run_id)
        second = service.run(
            context=synthetic_context(),
            task_text=task_text,
            query="Synthetic",
        )
        second_record = store.get(second.run_id)

        assert first.status is RunStatus.GENERATED
        assert first.result == fixture_result
        assert second.status is RunStatus.GENERATED
        assert second.run_id != first.run_id
        assert second_record is not None
        assert store.get(first.run_id) == first_record
        assert first_record is not None
        assert first_record.status is RunStatus.GENERATED
        assert first_record.retrieval_called is True
        assert first_record.model_called is True
        assert first_record.context.user_id == "synthetic-user-001"
        assert first_record.context.role_id == "synthetic-researcher"
        assert first_record.context.client_id == "synthetic-client-001"
        assert first_record.context.matter_id == "synthetic-matter-001"
        assert first_record.context.workflow_id == "synthetic-workflow-001"
        assert first_record.permission is not None
        assert first_record.permission.policy_id == "policy.synthetic-run.001"
        assert first_record.permission.policy_version == "1.0.0"
        assert first_record.configuration.provider_id == "fixture-model-provider"
        assert first_record.configuration.configuration_id == "p0-synthetic-run"
        assert first_record.configuration.configuration_version == "1.0.0"
        assert first_record.configuration.model_id == governed_model["id"]
        assert first_record.configuration.model_version == governed_model["version"]
        assert (
            first_record.configuration.model_content_hash
            == governed_model["content_hash"]
            == governed_fixture.content_hash
        )
        assert first_record.configuration_hash.startswith("sha256:")
        assert first_record.configuration_hash == governed_configuration_hash(
            first_record.configuration,
            policy(),
        )
        assert [
            (
                source.source_id,
                source.source_version,
                tuple(chunk.chunk_id for chunk in source.chunks),
            )
            for source in first_record.sources
        ] == [
            (
                governed_source["id"],
                governed_source["version"],
                (chunk_id.value,),
            )
        ]
        with pytest.raises(sqlite3.IntegrityError):
            store.append(first_record)
    finally:
        retrieval.close()
        store.close()

    with sqlite3.connect(provenance_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        column_names = {
            row[1]
            for table in (
                "runs",
                "run_configurations",
                "run_permission_conditions",
                "run_sources",
                "run_chunks",
                "model_executions",
            )
            for row in connection.execute(f"PRAGMA table_info({table})")
        }
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO run_chunks (
                    run_id, source_id, chunk_id, ordinal, retrieval_position
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (first.run_id.value, "wrong-source", "wrong-chunk", 0, 1),
            )
        with pytest.raises(sqlite3.IntegrityError, match="run_id is immutable"):
            connection.execute(
                "UPDATE runs SET run_id = ? WHERE run_id = ?",
                ("mutated-run-id", first.run_id.value),
            )
        assert connection.execute(
            "SELECT run_id FROM runs WHERE run_id = ?",
            (first.run_id.value,),
        ).fetchone() == (first.run_id.value,)
        assert (
            connection.execute(
                "SELECT run_id FROM runs WHERE run_id = 'mutated-run-id'"
            ).fetchone()
            is None
        )
    assert {"prompt", "query", "task_text", "source_text", "answer_text"}.isdisjoint(
        column_names
    )
    database_bytes = provenance_path.read_bytes()
    assert corpus_payload["text"].encode() not in database_bytes
    assert task_text.encode() not in database_bytes
    assert fixture_result.answer_text.encode() not in database_bytes


class InterleavedRetrieval:
    def __init__(self, chunks: tuple[RetrievedChunk, ...]) -> None:
        self.chunks = chunks

    def retrieve(
        self,
        query: str,
        access_scope: AccessScope,
        *,
        limit: int = 10,
    ) -> tuple[RetrievedChunk, ...]:
        return self.chunks


class CapturingModel:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ResearchResult:
        self.requests.append(request)
        return ResearchResult("Synthetic ordered result.")


def test_interleaved_retrieval_order_round_trips_through_sqlite(
    tmp_path: Path,
) -> None:
    chunks = (
        RetrievedChunk(
            SourceId("source-a"),
            ChunkId("source-a.chunk-001"),
            0,
            "Synthetic A",
            "first authorized chunk",
            source_version="1.0.0",
        ),
        RetrievedChunk(
            SourceId("source-b"),
            ChunkId("source-b.chunk-001"),
            0,
            "Synthetic B",
            "second authorized chunk",
            source_version="2.0.0",
        ),
        RetrievedChunk(
            SourceId("source-a"),
            ChunkId("source-a.chunk-002"),
            1,
            "Synthetic A",
            "third authorized chunk",
            source_version="1.0.0",
        ),
    )
    model = CapturingModel()
    database_path = tmp_path / "ordered-provenance.sqlite3"
    store = SQLiteProvenanceStore(database_path)
    try:
        service = RunService._from_components_for_testing(
            policy=policy(),
            retrieval_provider=InterleavedRetrieval(chunks),
            model_provider=model,
            provenance_store=store,
            configuration=run_configuration("ordered-fixture", "1.0.0"),
            run_id_factory=lambda: RunId("ordered-run"),
        )

        outcome = service.run(
            context=synthetic_context(),
            task_text="Preserve authorized retrieval order.",
            query="authorized",
        )
        persisted = store.get(outcome.run_id)

        assert outcome.status is RunStatus.GENERATED
        assert [
            (chunk.source_id, chunk.chunk_id)
            for chunk in model.requests[0].source_chunks
        ] == [
            ("source-a", "source-a.chunk-001"),
            ("source-b", "source-b.chunk-001"),
            ("source-a", "source-a.chunk-002"),
        ]
        assert persisted is not None
        assert [
            (source_id, chunk.chunk_id, chunk.ordinal, chunk.retrieval_position)
            for source_id, _source_version, chunk in (
                persisted.chunks_in_retrieval_order
            )
        ] == [
            ("source-a", "source-a.chunk-001", 0, 0),
            ("source-b", "source-b.chunk-001", 0, 1),
            ("source-a", "source-a.chunk-002", 1, 2),
        ]
    finally:
        store.close()

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT source_id, chunk_id, ordinal, retrieval_position
            FROM run_chunks WHERE run_id = ? ORDER BY retrieval_position
            """,
            (outcome.run_id.value,),
        ).fetchall()
        assert rows == [
            ("source-a", "source-a.chunk-001", 0, 0),
            ("source-b", "source-b.chunk-001", 0, 1),
            ("source-a", "source-a.chunk-002", 1, 2),
        ]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO run_chunks (
                    run_id, source_id, chunk_id, ordinal, retrieval_position
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (outcome.run_id.value, "source-a", "duplicate-position", 2, 1),
            )


class NeverRetrieval:
    def __init__(self) -> None:
        self.calls = 0

    def retrieve(
        self,
        query: str,
        access_scope: AccessScope,
        *,
        limit: int = 10,
    ) -> tuple[RetrievedChunk, ...]:
        self.calls += 1
        return ()


class NeverModel:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request: ModelRequest) -> ResearchResult:
        self.calls += 1
        return ResearchResult("Should not execute.")


def test_blocked_run_has_no_sqlite_retrieval_source_or_model_provenance(
    tmp_path: Path,
) -> None:
    provenance_path = tmp_path / "blocked.sqlite3"
    store = SQLiteProvenanceStore(provenance_path)
    retrieval = NeverRetrieval()
    model = NeverModel()
    try:
        service = RunService._from_components_for_testing(
            policy=policy("BLOCK"),
            retrieval_provider=retrieval,
            model_provider=model,
            provenance_store=store,
            configuration=run_configuration(
                "model-output.synthetic-happy-path.001",
                "1.0.0",
            ),
        )

        outcome = service.run(
            context=synthetic_context(),
            task_text="Synthetic task.",
            query="Synthetic",
        )
        record = store.get(outcome.run_id)

        assert outcome.status is RunStatus.PERMISSION_STOPPED
        assert retrieval.calls == 0
        assert model.calls == 0
        assert record is not None
        assert record.sources == ()
        assert record.retrieval_called is False
        assert record.model_called is False
    finally:
        store.close()

    with sqlite3.connect(provenance_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        assert connection.execute("SELECT count(*) FROM run_sources").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM run_chunks").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM model_executions"
        ).fetchone() == (0,)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO run_sources (run_id, source_id, source_version)
                VALUES (?, ?, ?)
                """,
                (outcome.run_id.value, "false-source", "1.0.0"),
            )
