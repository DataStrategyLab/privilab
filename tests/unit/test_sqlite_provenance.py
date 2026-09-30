import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.adapters.storage.sqlite_provenance import (
    _SCHEMA,
    _evaluation_json,
    _expected_schema,
    _options_json,
    _read_evaluation,
    _read_flag,
    _read_options,
    _read_timestamp,
    _unique_indexes,
    _validate_existing_schema,
)
from privilab.application import RunConfiguration, RunProvenance
from privilab.application.run_review import (
    EvaluationSnapshot,
    HumanReview,
    InvalidEvidence,
    ReviewConflict,
    ReviewDecision,
    RunReviewService,
)
from privilab.web.preview import (
    CONTEXT_CHOICES,
    QUERY,
    STANDARD_CONTEXT,
    TASK_TEXT,
    open_preview_run,
)


@pytest.mark.parametrize(
    "field", ["synthetic_context", "retrieval_called", "model_called"]
)
@pytest.mark.parametrize(
    "value, storage",
    [
        (None, "null"),
        ("0", "text"),
        ("1", "text"),
        ("false", "text"),
        (b"1", "blob"),
        (0.0, "real"),
        (1.0, "real"),
        (1.5, "real"),
        (-1, "integer"),
        (2, "integer"),
        (True, "integer"),
        (False, "integer"),
    ],
)
def test_r06_03_flag_validator_rejects_noncanonical_representations(
    field: str, value: object, storage: str
) -> None:
    with pytest.raises(ValueError, match=f"^stored {field} is invalid$"):
        _read_flag(value, storage, field)


@pytest.mark.parametrize(
    "field", ["synthetic_context", "retrieval_called", "model_called"]
)
@pytest.mark.parametrize("storage", ["text", "real", "blob", "null"])
def test_r06_03_flag_validator_requires_integer_storage(
    field: str, storage: str
) -> None:
    with pytest.raises(ValueError, match=f"^stored {field} is invalid$"):
        _read_flag(1, storage, field)


@pytest.mark.parametrize(
    "field", ["synthetic_context", "retrieval_called", "model_called"]
)
@pytest.mark.parametrize("value", [0, 1])
def test_r06_03_flag_validator_preserves_canonical_values(
    field: str, value: int
) -> None:
    if field == "synthetic_context" and value == 0:
        with pytest.raises(ValueError, match="^stored synthetic_context is invalid$"):
            _read_flag(value, "integer", field)
    else:
        assert _read_flag(value, "integer", field) is bool(value)


@pytest.mark.parametrize("field", ["started_at", "completed_at"])
@pytest.mark.parametrize("storage_class", ["blob", "integer", "real", "null"])
def test_review05_timestamp_parser_rejects_nontext_storage(
    field: str, storage_class: str
) -> None:
    with pytest.raises(ValueError, match=f"^stored {field} is invalid$"):
        _read_timestamp(b"2026-09-14T12:00:00.000000Z", storage_class, field)


@pytest.mark.parametrize("field", ["started_at", "completed_at"])
@pytest.mark.parametrize("value", [None, 1, 1.5, "2026-09-14T12:00:00.000000Z"])
def test_review05_timestamp_parser_requires_complete_byte_projection(
    field: str, value: object
) -> None:
    with pytest.raises(ValueError, match=f"^stored {field} is invalid$"):
        _read_timestamp(value, "text", field)


def test_review05_timestamp_parser_leaves_canonicalization_to_provenance() -> None:
    parsed = _read_timestamp(b"2026-09-14T13:30:00.123456+01:30", "text", "started_at")
    assert parsed.hour == 13
    assert parsed.minute == 30
    assert parsed.microsecond == 123456
    assert parsed.utcoffset() == timedelta(hours=1, minutes=30)
    assert parsed.astimezone(UTC) == datetime(2026, 9, 14, 12, 0, 0, 123456, UTC)


@pytest.mark.parametrize(
    "payload",
    [
        '{"x":"one","x":"two"}',
        r'{"x":"one","\u0078":"two"}',
        '{"x":"one","x":"one"}',
        r'{"x\u0000a":"one","x\u0000\u0061":"two"}',
        r'{"é":"one","\u00e9":"two"}',
    ],
)
def test_review03_read_options_rejects_duplicate_decoded_keys(payload: str) -> None:
    with pytest.raises(ValueError, match="^stored configuration options are invalid$"):
        _read_options(payload, "text")


@pytest.mark.parametrize("storage_class", ["blob", "integer", "real", "null"])
def test_post_r07_b_options_reader_requires_text_storage(storage_class: str) -> None:
    with pytest.raises(ValueError, match="^stored configuration options are invalid$"):
        _read_options('{"safe":"value"}', storage_class)


@pytest.mark.parametrize(
    "payload", [b'{"safe":"value"}', bytearray(b'{"safe":"value"}'), None, 1, 1.5]
)
def test_post_r07_b_options_reader_requires_string_before_parsing(
    payload: object,
) -> None:
    with pytest.raises(ValueError, match="^stored configuration options are invalid$"):
        _read_options(payload, "text")


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        '{"x":"one","X":"two"}',
        r'{"\u00e9":"caf\u00e9"}',
        r'{"x\u0000a":"one","x\u0000b":"two","x":"three"}',
    ],
)
def test_review03_read_options_preserves_distinct_decoded_keys(payload: str) -> None:
    assert _read_options(payload, "text") == tuple(sorted(json.loads(payload).items()))


@pytest.mark.parametrize("payload", ["not-json", "[]", "null", '{"x":1}', '{"x":{}}'])
def test_review03_read_options_rejects_invalid_structure(payload: str) -> None:
    with pytest.raises(ValueError):
        _read_options(payload, "text")


def test_review03_options_serialization_is_deterministic() -> None:
    options = (("é", "café"), ("x\x00a", "value"), ("X", "two"), ("x", "one"))
    serialized = []
    for ordered in (options, tuple(reversed(options)), tuple(sorted(options))):
        configuration = RunConfiguration(
            configuration_id="synthetic-options",
            configuration_version="1",
            provider_id="fixture-model-provider",
            provider_version="1",
            model_id="synthetic-model",
            model_version="1",
            retrieval_provider_id="sqlite-fts5",
            retrieval_provider_version="1",
            options=ordered,
        )
        serialized.append(_options_json(configuration))
        assert _read_options(serialized[-1], "text") == configuration.options
    assert serialized == ['{"X":"two","x":"one","x\\u0000a":"value","é":"café"}'] * 3


def test_review03_expected_catalog_is_immutable_cached_and_closes_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_connect = sqlite3.connect
    references: list[sqlite3.Connection] = []

    def record_reference(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        assert args == (":memory:",)
        connection: sqlite3.Connection = original_connect(*args, **kwargs)
        references.append(connection)
        return connection

    _expected_schema.cache_clear()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(sqlite3, "connect", record_reference)
            catalog = _expected_schema()
            assert _expected_schema() is catalog
        assert len(references) == 1
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            references[0].execute("SELECT 1")
        assert isinstance(catalog, tuple)
        assert all(
            isinstance(row, tuple) and all(isinstance(value, str) for value in row)
            for row in catalog.objects
        )
        assert {row[0] for row in catalog.objects} == {"table", "trigger"}
        assert sum(row[0] == "table" for row in catalog.objects) == 9
        assert isinstance(catalog.unique_indexes, tuple)
        assert len(catalog.unique_indexes) == 10
        assert tuple(
            (table, unique, origin, partial, tuple(c[2] for c in columns if c[5]))
            for table, unique, origin, partial, columns in catalog.unique_indexes
        ) == (
            ("human_reviews", 1, "pk", 0, ("run_id",)),
            ("model_executions", 1, "pk", 0, ("run_id",)),
            ("model_telemetry", 1, "pk", 0, ("run_id",)),
            ("run_chunks", 1, "pk", 0, ("run_id", "chunk_id")),
            ("run_chunks", 1, "u", 0, ("run_id", "retrieval_position")),
            ("run_configurations", 1, "pk", 0, ("run_id",)),
            ("run_evaluations", 1, "pk", 0, ("run_id",)),
            ("run_permission_conditions", 1, "pk", 0, ("run_id", "condition_id")),
            ("run_sources", 1, "pk", 0, ("run_id", "source_id")),
            ("runs", 1, "pk", 0, ("run_id",)),
        )
    finally:
        _expected_schema.cache_clear()


def test_review03_postvalidation_requires_nonempty_complete_schema() -> None:
    with closing(sqlite3.connect(":memory:")) as connection:
        _validate_existing_schema(connection, allow_empty=True)
        with pytest.raises(
            RuntimeError, match="^local provenance schema is incompatible;"
        ):
            _validate_existing_schema(connection)


@pytest.mark.parametrize("initialization", ["empty", "partial", "extra-unique"])
def test_review03_constructor_postvalidates_initialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, initialization: str
) -> None:
    database_path = tmp_path / "incomplete-initialization.sqlite3"
    original_connect = sqlite3.connect
    targets: list[sqlite3.Connection] = []

    class IncompleteInitialization(sqlite3.Connection):
        def executescript(self, sql_script: str, /) -> sqlite3.Cursor:
            if initialization != "empty":
                super().executescript(sql_script)
                if initialization == "partial":
                    self.execute("DROP TRIGGER prevent_run_id_update")
                else:
                    self.execute(
                        "CREATE UNIQUE INDEX extra ON runs(configuration_hash)"
                    )
            return self.cursor()

    def incomplete_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        if str(args[0]) == str(database_path):
            kwargs["factory"] = IncompleteInitialization
        connection: sqlite3.Connection = original_connect(*args, **kwargs)
        if str(args[0]) == str(database_path):
            targets.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", incomplete_connect)
    with pytest.raises(RuntimeError, match="^local provenance schema is incompatible;"):
        SQLiteProvenanceStore(database_path)
    assert len(targets) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        targets[0].execute("SELECT 1")


def test_review04_index_catalog_preserves_multiplicity_not_names_or_list_order() -> (
    None
):
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.executescript(_SCHEMA)
        baseline = _unique_indexes(connection, ("runs",))
        connection.execute("CREATE UNIQUE INDEX extra ON runs(configuration_hash)")
        one_extra = _unique_indexes(connection, ("runs",))
        connection.execute("CREATE UNIQUE INDEX duplicate ON runs(configuration_hash)")
        two_extra = _unique_indexes(connection, ("runs",))
        assert len(two_extra) == len(one_extra) + 1 == len(baseline) + 2
        assert two_extra[0] == two_extra[1] == one_extra[0]
        assert two_extra[0] == (
            "runs",
            1,
            "c",
            0,
            (
                (0, 16, "configuration_hash", 0, "BINARY", 1),
                (1, 0, "run_id", 0, "BINARY", 0),
            ),
        )
        connection.execute("CREATE INDEX harmless ON runs(started_at)")
        assert _unique_indexes(connection, ("runs",)) == two_extra
        connection.execute("DROP INDEX duplicate")
        connection.execute(
            'CREATE UNIQUE INDEX "renamed\'index" ON runs(configuration_hash)'
        )
        assert _unique_indexes(connection, ("runs",)) == two_extra


@pytest.mark.parametrize("failure", ["ddl", "metadata"])
def test_review04_reference_connection_closes_on_failure(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    original_connect = sqlite3.connect
    references: list[sqlite3.Connection] = []

    class FailingReference(sqlite3.Connection):
        def executescript(self, sql_script: str, /) -> sqlite3.Cursor:
            if failure == "ddl":
                raise sqlite3.DatabaseError("synthetic reference failure")
            return super().executescript(sql_script)

        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            if "pragma_index_list" in sql:
                raise sqlite3.DatabaseError("synthetic reference metadata failure")
            return super().execute(sql, parameters)

    def failing_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        assert args == (":memory:",)
        connection = original_connect(*args, **kwargs, factory=FailingReference)
        references.append(connection)
        return connection

    _expected_schema.cache_clear()
    try:
        monkeypatch.setattr(sqlite3, "connect", failing_connect)
        with pytest.raises(sqlite3.DatabaseError, match="synthetic reference"):
            _expected_schema()
        assert _expected_schema.cache_info().currsize == 0
        assert len(references) == 1
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            references[0].execute("SELECT 1")
    finally:
        _expected_schema.cache_clear()


@pytest.mark.parametrize(
    ("metadata", "mutation"),
    [
        ("list", "missing"),
        ("list", "uniqueness"),
        ("list", "origin"),
        ("list", "partial"),
        ("list", "name"),
        ("list", "unreadable"),
        ("xinfo", "unreadable"),
        ("xinfo", "missing"),
        ("xinfo", "expression"),
        ("xinfo", "sequence"),
        ("xinfo", "column-id"),
        ("xinfo", "column-name"),
        ("xinfo", "descending"),
        ("xinfo", "collation"),
        ("xinfo", "key-participation"),
        ("xinfo", "duplicate"),
    ],
)
def test_review04_unreadable_or_inconsistent_metadata_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metadata: str, mutation: str
) -> None:
    database_path = tmp_path / "metadata.sqlite3"
    SQLiteProvenanceStore(database_path).close()
    original_connect = sqlite3.connect
    before = database_path.read_bytes()
    with closing(original_connect(database_path)) as connection:
        schema = connection.execute(
            "SELECT * FROM sqlite_schema ORDER BY name"
        ).fetchall()
    statements: list[str] = []
    targets: list[sqlite3.Connection] = []

    class InconsistentMetadata(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            if f"pragma_index_{metadata}" in sql:
                if mutation == "unreadable":
                    raise sqlite3.DatabaseError("synthetic unreadable metadata")
                if mutation == "missing":
                    return super().execute(f"SELECT * FROM ({sql}) WHERE 0", parameters)
                if mutation == "duplicate":
                    return super().execute(
                        f"WITH entries AS ({sql}) "
                        "SELECT * FROM entries UNION ALL SELECT * FROM entries",
                        parameters,
                    )
                original, replacement = {
                    "uniqueness": ('"unique"', "0"),
                    "origin": ("origin", "'c'"),
                    "partial": ("partial", "1"),
                    "name": ("name", "NULL"),
                    "expression": ("cid", "-2"),
                    "sequence": ("seqno", "seqno + 1"),
                    "column-id": ("cid", "cid + 1"),
                    "column-name": ("name", "'wrong_column'"),
                    "descending": ('"desc"', '1 - "desc"'),
                    "collation": ("coll", "'NOCASE'"),
                    "key-participation": ('"key"', '1 - "key"'),
                }[mutation]
                # Change exactly one metadata field, retaining all other rows
                # and fields so rejection cannot be due to an incomplete index.
                return super().execute(
                    sql.replace(original, replacement, 1), parameters
                )
            return super().execute(sql, parameters)

    def inconsistent_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        assert str(args[0]) == str(database_path)
        connection = original_connect(*args, **kwargs, factory=InconsistentMetadata)
        connection.set_trace_callback(statements.append)
        targets.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", inconsistent_connect)
    with pytest.raises(
        RuntimeError,
        match="^local provenance schema is incompatible; a fresh database is required$",
    ):
        SQLiteProvenanceStore(database_path)
    assert len(targets) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        targets[0].execute("SELECT 1")
    assert not any(
        sql.lstrip().upper().startswith(("CREATE", "ALTER", "DROP"))
        for sql in statements
    )
    with closing(original_connect(database_path)) as connection:
        assert (
            connection.execute("SELECT * FROM sqlite_schema ORDER BY name").fetchall()
            == schema
        )
    assert database_path.read_bytes() == before


@pytest.fixture
def evidence_snapshot() -> tuple[RunProvenance, EvaluationSnapshot]:
    with open_preview_run() as (runner, store):
        _, view = RunReviewService(store, store).execute(
            runner, context=STANDARD_CONTEXT, task_text=TASK_TEXT, query=QUERY
        )
        assert view.evaluation is not None
        return view.run, view.evaluation


def test_evidence_round_trip_duplicate_and_foreign_key_integrity(
    tmp_path: Path, evidence_snapshot: tuple[RunProvenance, EvaluationSnapshot]
) -> None:
    run, snapshot = evidence_snapshot
    path = tmp_path / "evidence.sqlite3"
    review = HumanReview(run.run_id, ReviewDecision.APPROVE, datetime.now(UTC))
    with closing(SQLiteProvenanceStore(path)) as store:
        assert store._connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            store.append_evaluation(snapshot)
        with pytest.raises(sqlite3.IntegrityError):
            store.append_review(review)
        store.append(run)
        with pytest.raises(sqlite3.IntegrityError):
            store.append_review(review)
        store.append_evaluation(snapshot)
        with pytest.raises(sqlite3.IntegrityError):
            store.append_evaluation(snapshot)
        store.append_review(review)
        with pytest.raises(ReviewConflict):
            store.append_review(review)
        assert store.get(run.run_id) == run
        assert store.get_evaluation(run.run_id) == snapshot
    with closing(SQLiteProvenanceStore(path)) as store:
        assert store._connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert store.get_evaluation(run.run_id) == snapshot
        assert store.get_review(run.run_id) == review


@pytest.mark.parametrize("table", ["run_evaluations", "human_reviews"])
@pytest.mark.parametrize(
    "operation", ["UPDATE", "DELETE", "REPLACE", "INSERT OR REPLACE"]
)
@pytest.mark.parametrize("recursive", [0, 1])
def test_evidence_records_prevent_mutation_and_replacement(
    evidence_snapshot: tuple[RunProvenance, EvaluationSnapshot],
    table: str,
    operation: str,
    recursive: int,
) -> None:
    run, snapshot = evidence_snapshot
    with closing(SQLiteProvenanceStore(":memory:")) as store:
        store.append(run)
        store.append_evaluation(snapshot)
        store.append_review(
            HumanReview(run.run_id, ReviewDecision.REJECT, datetime.now(UTC))
        )
        connection = store._connection
        connection.execute(f"PRAGMA recursive_triggers={recursive}")
        before = tuple(connection.iterdump())
        statement = {
            "UPDATE": f"UPDATE {table} SET run_id=run_id",
            "DELETE": f"DELETE FROM {table}",
            "REPLACE": f"REPLACE INTO {table} SELECT * FROM {table}",
            "INSERT OR REPLACE": (
                f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}"
            ),
        }[operation]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(statement)
        assert tuple(connection.iterdump()) == before


def test_storage_has_no_generated_or_pass_eligibility_policy() -> None:
    for scenario in ("critical-citation-failure", "blocked-role"):
        context = next(
            context for key, _, context in CONTEXT_CHOICES if key == scenario
        )
        with open_preview_run(context_choice=scenario) as (runner, store):
            _, view = RunReviewService(store, store).execute(
                runner, context=context, task_text=TASK_TEXT, query=QUERY
            )
            assert view.evaluation is not None
            # Deliberate direct adapter call: integrity permits it; the application
            # must reject the same request and hide contradictory stored decisions.
            review = HumanReview(
                view.run.run_id, ReviewDecision.APPROVE, datetime.now(UTC)
            )
            store.append_review(review)
            assert store.get_review(view.run.run_id) == review
            assert (
                RunReviewService(store, store).get(view.run.run_id).review_state
                == "NOT REVIEWABLE"
            )


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "missing",
        "schema",
        "cross-run",
        "timestamp",
        "naive-time",
        "kind",
        "version",
        "status",
        "criticality",
        "count-type",
        "count-bound",
        "codes",
        "reason",
        "pass-block",
        "block-pass",
        "block-reference",
        "duplicate-criteria",
    ],
)
def test_strict_snapshot_deserialization(
    evidence_snapshot: tuple[RunProvenance, EvaluationSnapshot], mutation: str
) -> None:
    run, snapshot = evidence_snapshot
    payload = json.loads(_evaluation_json(snapshot))
    criterion = payload["criteria"][0]
    if mutation == "extra":
        payload["answer_text"] = "forbidden"
    elif mutation == "missing":
        del payload["task_id"]
    elif mutation == "schema":
        payload["schema_version"] = "2"
    elif mutation == "cross-run":
        payload["run_id"] = "other-run"
    elif mutation == "timestamp":
        payload["evaluated_at"] = "not a timestamp"
    elif mutation == "naive-time":
        payload["evaluated_at"] = "2026-09-21T12:00:00"
    elif mutation == "kind":
        criterion["evaluator_kind"] = "live-model"
    elif mutation == "version":
        criterion["evaluator_version"] = "99"
    elif mutation == "status":
        criterion["status"] = "APPROVE"
    elif mutation == "criticality":
        criterion["criticality"] = "NON_CRITICAL"
    elif mutation == "count-type":
        criterion["evidence"]["source_count"] = True
    elif mutation == "count-bound":
        criterion["evidence"]["citation_count"] = 2**64
    elif mutation == "codes":
        criterion["evidence"]["reason_codes"] *= 2
    elif mutation == "reason":
        criterion["evidence"]["reason_codes"] = ["SOURCE_NOT_IN_RUN_CONTEXT"]
    elif mutation == "pass-block":
        payload["blocks"] = [
            {
                "reason_code": "OUTPUT_GATE_INELIGIBLE",
                "criterion_id": None,
                "criterion_version": None,
            }
        ]
    elif mutation == "block-pass":
        payload["gate_status"] = "BLOCK"
    elif mutation == "block-reference":
        payload["gate_status"] = "BLOCK"
        payload["blocks"] = [
            {
                "reason_code": "CRITICAL_CRITERION_NOT_PASS",
                "criterion_id": "missing",
                "criterion_version": "1.0.0",
            }
        ]
    else:
        payload["criteria"][1] = criterion
    with pytest.raises(InvalidEvidence):
        _read_evaluation(json.dumps(payload), run.run_id)


def test_duplicate_json_fields_and_nontext_storage_rejected(
    evidence_snapshot: tuple[RunProvenance, EvaluationSnapshot],
) -> None:
    run, snapshot = evidence_snapshot
    payload = _evaluation_json(snapshot)
    for invalid in (
        payload.replace(
            '"schema_version":"1"', '"schema_version":"1","schema_version":"1"'
        ),
        payload.encode(),
        "[]",
        "null",
        "{}",
    ):
        with pytest.raises(InvalidEvidence):
            _read_evaluation(invalid, run.run_id)


def test_legacy_schema_rejected_without_repair(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    with closing(SQLiteProvenanceStore(path)):
        pass
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("DROP TABLE human_reviews")
        connection.execute("DROP TABLE run_evaluations")
        connection.commit()
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="incompatible"):
        SQLiteProvenanceStore(path)
    assert path.read_bytes() == before


def test_failed_schema_creation_rolls_back_all_ddl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "atomic-schema.sqlite3"
    _expected_schema()
    connect = sqlite3.connect

    class InterruptedSchema(sqlite3.Connection):
        def executescript(self, sql_script: str, /) -> sqlite3.Cursor:
            return super().executescript(sql_script + "\nINVALID DDL;")

    def failing_connection(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        return connect(*args, **kwargs, factory=InterruptedSchema)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", failing_connection)
        with pytest.raises(sqlite3.OperationalError):
            SQLiteProvenanceStore(path)
    with closing(connect(path)) as connection:
        assert connection.execute("SELECT name FROM sqlite_schema").fetchall() == []
    with closing(SQLiteProvenanceStore(path)) as store:
        assert store.recent_run_ids() == ()
