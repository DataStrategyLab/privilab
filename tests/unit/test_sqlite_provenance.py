import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.adapters.storage.sqlite_provenance import (
    _expected_schema,
    _options_json,
    _read_options,
    _validate_existing_schema,
)
from privilab.application import RunConfiguration


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
        _read_options(payload)


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
    assert _read_options(payload) == tuple(sorted(json.loads(payload).items()))


@pytest.mark.parametrize("payload", ["not-json", "[]", "null", '{"x":1}', '{"x":{}}'])
def test_review03_read_options_rejects_invalid_structure(payload: str) -> None:
    with pytest.raises(ValueError):
        _read_options(payload)


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
        assert _read_options(serialized[-1]) == configuration.options
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
            for row in catalog
        )
        assert {row[0] for row in catalog} == {"table", "trigger"}
        assert sum(row[0] == "table" for row in catalog) == 6
    finally:
        _expected_schema.cache_clear()


def test_review03_postvalidation_requires_nonempty_complete_schema() -> None:
    with closing(sqlite3.connect(":memory:")) as connection:
        _validate_existing_schema(connection, allow_empty=True)
        with pytest.raises(
            RuntimeError, match="^local provenance schema is incompatible;"
        ):
            _validate_existing_schema(connection)


@pytest.mark.parametrize("initialization", ["empty", "partial"])
def test_review03_constructor_postvalidates_initialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, initialization: str
) -> None:
    database_path = tmp_path / "incomplete-initialization.sqlite3"
    original_connect = sqlite3.connect
    targets: list[sqlite3.Connection] = []

    class IncompleteInitialization(sqlite3.Connection):
        def executescript(self, sql_script: str, /) -> sqlite3.Cursor:
            if initialization == "partial":
                super().executescript(sql_script)
                self.execute("DROP TRIGGER prevent_run_id_update")
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
