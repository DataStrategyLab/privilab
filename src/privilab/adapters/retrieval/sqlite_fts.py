"""Local SQLite/FTS5 retrieval with SQL-enforced exact entitlements."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from functools import cache
from itertools import batched, groupby, islice, product
from operator import itemgetter
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import NamedTuple

from privilab.domain.retrieval import (
    AccessScope,
    ChunkId,
    RetrievalSource,
    RetrievedChunk,
    SourceId,
)

_MAX_LIMIT = 100
_FTS_TOKEN_BYTE_LIMIT = 32768
_FTS5_QUERY_ERROR_MARKERS = (
    "fts5: syntax error",
    "fts5: parser stack overflow",
    "unterminated string",
    "unknown special query:",
    "expected integer, got",
)

_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    source_version TEXT NOT NULL,
    title TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_entitlements (
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    user_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    client_id TEXT NOT NULL,
    matter_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    UNIQUE (source_id, user_id, role_id, client_id, matter_id, workflow_id)
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    text TEXT NOT NULL,
    UNIQUE (source_id, ordinal)
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    text
);
"""

_RETRIEVAL_TABLES = ("sources", "source_entitlements", "chunks", "chunks_fts")
_INCOMPATIBLE_SCHEMA_MESSAGE = (
    "local retrieval index schema is incompatible and must be recreated or rebuilt"
)

_RETRIEVE_SQL = """
WITH authorized_sources AS (
    SELECT source_id
    FROM source_entitlements
    WHERE user_id = ?
      AND role_id = ?
      AND client_id = ?
      AND matter_id = ?
      AND workflow_id = ?
), authorized_chunks AS (
    SELECT chunks.source_id, chunks.chunk_id, chunks.ordinal, chunks.text
    FROM chunks
    JOIN authorized_sources ON authorized_sources.source_id = chunks.source_id
), authorized_matches AS (
    SELECT authorized_chunks.source_id, authorized_chunks.chunk_id,
           authorized_chunks.ordinal,
           (
               length(highlight(chunks_fts, 1, char(1), char(2)))
               - length(authorized_chunks.text)
           ) / 2.0 AS match_count
    FROM chunks_fts
    JOIN authorized_chunks ON authorized_chunks.chunk_id = chunks_fts.chunk_id
    WHERE chunks_fts MATCH ?
), scored_matches AS (
    SELECT authorized_matches.source_id, authorized_matches.chunk_id,
           authorized_matches.ordinal,
           authorized_matches.match_count * 1.0
           / length(authorized_chunks.text) AS score
    FROM authorized_matches
    JOIN authorized_chunks
      ON authorized_chunks.chunk_id = authorized_matches.chunk_id
)
SELECT scored_matches.source_id,
       sources.source_version,
       scored_matches.chunk_id,
       scored_matches.ordinal,
       sources.title,
       chunks.text
FROM scored_matches
JOIN sources ON sources.source_id = scored_matches.source_id
JOIN chunks ON chunks.chunk_id = scored_matches.chunk_id
ORDER BY scored_matches.score DESC, scored_matches.source_id,
         scored_matches.ordinal, scored_matches.chunk_id
LIMIT ?
"""


def _is_fts5_query_error(error: sqlite3.OperationalError, query: str) -> bool:
    """Return whether SQLite rejected the bound MATCH expression syntax."""
    error_message = str(error).lower()
    if any(marker in error_message for marker in _FTS5_QUERY_ERROR_MARKERS):
        return True
    if not error_message.startswith("no such column:"):
        return False
    missing_column = error_message.partition(":")[2].strip()
    escaped_column = re.escape(missing_column)
    return (
        bool(missing_column)
        and re.search(
            rf"(?<!\w)(?:{escaped_column}|\"{escaped_column}\"|"
            rf"\{{{escaped_column}(?:\s+\w+)*\}})\s*:",
            query,
            flags=re.IGNORECASE,
        )
        is not None
    )


def _validate_query(query: object) -> str:
    """Validate untrusted FTS input before handing it to SQLite."""
    if not isinstance(query, str):
        raise TypeError("query must be a string")
    if not query or query != query.strip():
        raise ValueError("query must be a non-empty, trimmed string")
    if "\x00" in query:
        raise ValueError("query must not contain NUL characters")
    try:
        query.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("query must be UTF-8 encodable") from error
    return query


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _metadata_rows(cursor: sqlite3.Cursor) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(value.lower() if isinstance(value, str) else value for value in row)
        for row in cursor
    )


def _table_structure(connection: sqlite3.Connection, table: str) -> tuple[object, ...]:
    """Current-runtime structure, including hidden columns and conflict identities."""
    quoted = _quote_identifier(table)
    layout = _metadata_rows(
        connection.execute(
            "SELECT type, ncol, wr, strict FROM pragma_table_list "
            "WHERE schema = 'main' AND name = ? COLLATE NOCASE",
            (table,),
        )
    )
    columns = _metadata_rows(connection.execute(f"PRAGMA table_xinfo({quoted})"))
    foreign_keys = _metadata_rows(
        connection.execute(f"PRAGMA foreign_key_list({quoted})")
    )
    indexes = []
    for index in connection.execute(f"PRAGMA index_list({quoted})"):
        if not index[2]:
            continue
        indexes.append(
            (
                index[2],
                index[3],
                index[4],
                _metadata_rows(
                    connection.execute(
                        f"PRAGMA index_xinfo({_quote_identifier(index[1])})"
                    )
                ),
            )
        )
    return layout, columns, foreign_keys, tuple(sorted(indexes, key=repr))


def _schema_definition(connection: sqlite3.Connection, name: str) -> str | None:
    row = connection.execute(
        "SELECT type, sql FROM sqlite_schema WHERE name = ? COLLATE NOCASE",
        (name,),
    ).fetchone()
    if row is None or row[0] != "table" or not isinstance(row[1], str):
        return None
    return row[1]


def _normalize_schema_definition(definition: str) -> str:
    return re.sub(r"\s+", "", definition).casefold()


def _table_declarations(definition: str, table: str) -> tuple[str, ...]:
    """Bounded static grammar: preserve constraints, allow only BINARY/default ABORT.

    SQLite does not expose column collations, CHECK expressions or conflict
    actions as structured metadata. Compare these declarations with our trusted
    reference, never execute target SQL. Quotes/comments/unknown syntax fail closed.
    """
    if re.fullmatch(r"[\w\s(),>=]+", definition, re.ASCII) is None:
        raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
    match = re.fullmatch(
        rf"CREATE\s+TABLE\s+{re.escape(table)}\s*\((.*)\)",
        definition,
        re.IGNORECASE | re.ASCII | re.DOTALL,
    )
    if match is None:
        raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
    declarations: list[str] = []
    depth = start = 0
    body = match[1]
    for index, character in enumerate(body):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            declarations.append(body[start:index].strip())
            start = index + 1
        if depth < 0 or depth > 2:
            raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
    if depth != 0:
        raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
    declarations.append(body[start:].strip())
    normalized = []
    for clause in declarations:
        # At most one collation per column declaration; UNIQUE key collations
        # are independently checked through index_xinfo.
        unique = re.match(r"UNIQUE\s*\(", clause, re.IGNORECASE | re.ASCII)
        clause = re.sub(
            r"\bCOLLATE\s+BINARY\b",
            "",
            clause,
            count=0 if unique else 1,
            flags=re.IGNORECASE | re.ASCII,
        )
        if unique or re.search(r"\bPRIMARY\s+KEY\b", clause, re.IGNORECASE | re.ASCII):
            clause = re.sub(
                r"\bON\s+CONFLICT\s+ABORT\b",
                "",
                clause,
                count=1,
                flags=re.IGNORECASE | re.ASCII,
            )
        normalized.append(_normalize_schema_definition(clause))
    return tuple(normalized)


class _SchemaCatalog(NamedTuple):
    objects: tuple[tuple[str, str, str], ...]
    structures: tuple[tuple[str, tuple[object, ...]], ...]
    declarations: tuple[tuple[str, tuple[str, ...]], ...]
    fts_definition: str


@cache
def _expected_schema() -> _SchemaCatalog:
    """Derive immutable expectations solely from our SQL in the same runtime."""
    with closing(sqlite3.connect(":memory:")) as reference:
        reference.executescript(_SCHEMA)
        objects = tuple(
            reference.execute(
                "SELECT type, name, tbl_name FROM sqlite_schema "
                "WHERE type IN ('table', 'trigger') ORDER BY type, name"
            )
        )
        tables = tuple(row[1] for row in objects if row[0] == "table")
        declarations = []
        for table in _RETRIEVAL_TABLES:
            definition = _schema_definition(reference, table)
            if definition is None:
                raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
            if table != "chunks_fts":
                declarations.append((table, _table_declarations(definition, table)))
        fts = _schema_definition(reference, "chunks_fts")
        if fts is None:
            raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
        return _SchemaCatalog(
            objects,
            tuple((table, _table_structure(reference, table)) for table in tables),
            tuple(declarations),
            _normalize_schema_definition(fts),
        )


def _governed_objects(
    connection: sqlite3.Connection,
) -> tuple[tuple[str, str, str], ...]:
    names = tuple(row[1] for row in _expected_schema().objects)
    parameters = ", ".join("?" for _ in names)
    rows = connection.execute(
        f"SELECT type, name, tbl_name FROM sqlite_schema "
        f"WHERE name COLLATE NOCASE IN ({parameters}) "
        f"OR (type = 'trigger' AND tbl_name COLLATE NOCASE IN ({parameters}))",
        names + names,
    )
    return tuple(
        sorted((kind, name.lower(), table.lower()) for kind, name, table in rows)
    )


def _validate_schema_compatibility(connection: sqlite3.Connection) -> None:
    try:
        expected = _expected_schema()
        if _governed_objects(connection) != expected.objects:
            raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
        for table, structure in expected.structures:
            if _table_structure(connection, table) != structure:
                raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
        for table, declarations in expected.declarations:
            definition = _schema_definition(connection, table)
            if (
                definition is None
                or _table_declarations(definition, table) != declarations
            ):
                raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
        fts = _schema_definition(connection, "chunks_fts")
        if fts is None or _normalize_schema_definition(fts) != expected.fts_definition:
            raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
        # Real reads, not LIMIT 0 or an FTS control write. Structure validation
        # above also catches broken shadows on empty indexes.
        connection.execute("SELECT chunk_id, text FROM chunks_fts LIMIT 1").fetchall()
        connection.execute(
            """
            SELECT rowid
            FROM chunks_fts
            WHERE chunks_fts MATCH ?
            LIMIT 1
            """,
            ('"schema-compatibility-check"',),
        ).fetchall()
        # Compare all governed entries, not a sampled/possibly absent token.
        # FTS content must represent each application chunk exactly once, with
        # identical text. This read-only multiset comparison also finds missing
        # content rows while their index postings remain. It needs no tokenizer
        # assumptions, target writes, or FTS control commands.
        inconsistent_content = connection.execute(
            """
            SELECT 1
            FROM (
                SELECT chunk_id, text, 1 AS balance FROM chunks
                UNION ALL
                SELECT chunk_id, text, -1 AS balance FROM chunks_fts
            )
            GROUP BY chunk_id, text
            HAVING sum(balance) != 0
            LIMIT 1
            """
        ).fetchone()
        if inconsistent_content is not None:
            raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
    except sqlite3.DatabaseError:
        # SQLite decoding diagnostics can contain indexed content.
        raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE) from None


def _has_existing_retrieval_schema(connection: sqlite3.Connection) -> bool:
    try:
        return bool(_governed_objects(connection))
    except sqlite3.DatabaseError as error:
        raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE) from error


def _fts_boundary_candidates(raw: bytes) -> Iterator[str]:
    """Enumerate every legal scalar completion of a boundary-truncated term."""
    try:
        raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        if (
            len(raw) != _FTS_TOKEN_BYTE_LIMIT
            or error.reason != "unexpected end of data"
            or error.end != len(raw)
        ):
            raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE) from None
        # Strict decoding has validated the entire preceding text and rejected
        # illegal/overlong/surrogate/out-of-range prefixes before reaching here.
        prefix = raw[: error.start].decode("utf-8", errors="strict")
        suffix = raw[error.start :]
    else:
        raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
    width = 2 if suffix[0] < 0xE0 else 3 if suffix[0] < 0xF0 else 4

    def candidates() -> Iterator[str]:
        # Lexicographic continuation bytes give deterministic scalar order.
        # The finite Cartesian product is exhaustive, not a heuristic/cap.
        for ending in product(range(0x80, 0xC0), repeat=width - len(suffix)):
            try:
                scalar = (suffix + bytes(ending)).decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                continue
            yield prefix + scalar

    return candidates()


def _fts_match_term(clone: sqlite3.Connection, raw: bytes) -> str:
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        candidates = _fts_boundary_candidates(raw)

    # Lazy, clone-only, default-tokenizer scratch objects are reused across
    # boundary terms. Normal UTF-8 terms never need this sub-path.
    clone.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS temp._privilab_fts_completion_scratch "
        "USING fts5(text)"
    ).close()
    clone.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS temp._privilab_fts_completion_vocab "
        "USING fts5vocab(temp, '_privilab_fts_completion_scratch', 'instance')"
    ).close()
    for batch in batched(candidates, 256, strict=False):
        verified = None
        clone.execute("SAVEPOINT _privilab_fts_completion_batch").close()
        body_failed = False
        try:
            clone.executemany(
                "INSERT INTO temp._privilab_fts_completion_scratch(rowid, text) "
                "VALUES (?, ?)",
                enumerate(batch, 1),
            ).close()
            with closing(
                clone.execute(
                    """
                    SELECT doc, typeof(term), CAST(term AS BLOB)
                    FROM temp._privilab_fts_completion_vocab
                    WHERE col = 'text'
                    ORDER BY doc, offset
                    """
                )
            ) as vocabulary:
                for rowid, entries in groupby(vocabulary, key=itemgetter(0)):
                    if type(rowid) is not int or not 1 <= rowid <= len(batch):
                        raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
                    tokens = tuple(islice(entries, 2))
                    _, storage, token = tokens[0]
                    if storage != "text" or type(token) is not bytes:
                        raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
                    # Exactly one token occurrence, with exactly the original
                    # bytes; apparent prefix/length/category is insufficient.
                    if len(tokens) == 1 and token == raw:
                        verified = batch[rowid - 1]
                        break
        except Exception:
            body_failed = True
            raise
        finally:
            cleanup_error: Exception | None = None
            for statement in (
                "ROLLBACK TO _privilab_fts_completion_batch",
                "RELEASE _privilab_fts_completion_batch",
            ):
                try:
                    clone.execute(statement).close()
                except Exception as error:
                    # Always try RELEASE, including after SQLite auto-rollback.
                    # Without a body failure, retain cleanup resource exhaustion
                    # over a SQLite error so it cannot become incompatibility.
                    if cleanup_error is None or (
                        isinstance(error, MemoryError)
                        and not isinstance(cleanup_error, MemoryError)
                    ):
                        cleanup_error = error
            # An in-flight body exception keeps its original identity/precedence.
            # Otherwise cleanup must succeed before returning any candidate.
            if not body_failed and cleanup_error is not None:
                raise cleanup_error
        if verified is not None:
            return verified
        # Release this batch before batched() constructs the next one.
        del batch
    raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)


def _validate_fts_navigation(clone: sqlite3.Connection) -> None:
    """Compare sequential vocabulary postings with ordinary lookup on the clone."""
    try:
        clone.execute(
            "CREATE VIRTUAL TABLE temp._privilab_fts_validation_vocab "
            "USING fts5vocab(main, 'chunks_fts', 'instance')"
        )
        with closing(
            clone.execute(
                """
                SELECT typeof(term), CAST(term AS BLOB), doc
                FROM temp._privilab_fts_validation_vocab
                WHERE col = 'text'
                GROUP BY typeof(term), CAST(term AS BLOB), doc
                ORDER BY CAST(term AS BLOB), doc
                """
            )
        ) as expected:
            # groupby holds only the current term and one lookahead row. Neither
            # postings nor the complete vocabulary are accumulated in Python.
            for (storage, raw), documents in groupby(expected, key=itemgetter(0, 1)):
                if (
                    storage != "text"
                    or type(raw) is not bytes
                    or not 0 < len(raw) <= _FTS_TOKEN_BYTE_LIMIT
                ):
                    raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
                term = _fts_match_term(clone, raw)
                if "\x00" in term:
                    raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
                expression = 'text : "' + term.replace('"', '""') + '"'
                with closing(
                    clone.execute(
                        """
                        SELECT rowid
                        FROM main.chunks_fts
                        WHERE chunks_fts MATCH ?
                        ORDER BY rowid
                        """,
                        (expression,),
                    )
                ) as actual:
                    for _, _, doc in documents:
                        row = actual.fetchone()
                        if (
                            type(doc) is not int
                            or row is None
                            or type(row[0]) is not int
                            or row[0] != doc
                        ):
                            raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
                    if actual.fetchone() is not None:
                        raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
    except (sqlite3.DatabaseError, UnicodeError):
        # SQLite/query/encoding diagnostics may contain indexed text. Preserve
        # the generic readiness contract without rendering that exception chain.
        raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE) from None


def _validate_fts_integrity(connection: sqlite3.Connection) -> None:
    """Run the native control command only on a physical, disposable clone."""
    # Bound backup's own retry loop, independently of connection timeouts:
    # at most five BUSY/LOCKED callbacks, 10ms between retries, and a five-second
    # deadline checked after each step of at most 256 pages. This is a cooperative
    # step bound, not an interrupt of an individual native SQLite operation.
    deadline = monotonic() + 5.0
    busy_steps = 0

    def progress(status: int, remaining: int, total: int) -> None:
        nonlocal busy_steps
        if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            busy_steps += 1
        if busy_steps >= 5 or monotonic() >= deadline:
            raise sqlite3.OperationalError("retrieval validation backup limit exceeded")

    try:
        with closing(sqlite3.connect(":memory:", timeout=0)) as clone:
            connection.backup(clone, pages=256, progress=progress, sleep=0.01)
            _validate_schema_compatibility(clone)
            clone.execute(
                "INSERT INTO chunks_fts(chunks_fts) VALUES('integrity-check')"
            )
            _validate_fts_navigation(clone)
    except sqlite3.DatabaseError as error:
        raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE) from error


class SQLiteFtsRetrievalProvider:
    """Trusted local index administration plus authorization-scoped retrieval."""

    def __init__(self, database_path: str | Path) -> None:
        if not isinstance(database_path, (str, Path)):
            raise TypeError("database_path must be a string or Path")
        self._lock = RLock()
        self._connection = sqlite3.connect(str(database_path), check_same_thread=False)
        try:
            with self._lock:
                self._connection.execute("PRAGMA foreign_keys = ON")
                existing = _has_existing_retrieval_schema(self._connection)
                if existing:
                    _validate_schema_compatibility(self._connection)
                    _validate_fts_integrity(self._connection)
                self._connection.executescript(_SCHEMA)
                _validate_schema_compatibility(self._connection)
                if not existing:
                    _validate_fts_integrity(self._connection)
        except Exception:
            self._connection.close()
            raise

    def close(self) -> None:
        """Close the provider's local database connection."""
        with self._lock:
            self._connection.close()

    def index_source(self, source: RetrievalSource) -> None:
        """Atomically index trusted source metadata, chunks, and entitlements."""
        if not isinstance(source, RetrievalSource):
            raise TypeError("source must be a RetrievalSource")
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO sources (source_id, source_version, title)
                VALUES (?, ?, ?)
                """,
                (source.source_id.value, source.source_version, source.title),
            )
            self._connection.executemany(
                """
                INSERT INTO source_entitlements (
                    source_id, user_id, role_id, client_id, matter_id, workflow_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        entitlement.source_id.value,
                        entitlement.user_id,
                        entitlement.role_id,
                        entitlement.client_id,
                        entitlement.matter_id,
                        entitlement.workflow_id,
                    )
                    for entitlement in source.entitlements
                ],
            )
            self._connection.executemany(
                """
                INSERT INTO chunks (chunk_id, source_id, ordinal, text)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        chunk.chunk_id.value,
                        chunk.source_id.value,
                        chunk.ordinal,
                        chunk.text,
                    )
                    for chunk in source.chunks
                ],
            )
            self._connection.executemany(
                "INSERT INTO chunks_fts (chunk_id, text) VALUES (?, ?)",
                [(chunk.chunk_id.value, chunk.text) for chunk in source.chunks],
            )

    def retrieve(
        self,
        query: str,
        access_scope: AccessScope,
        *,
        limit: int = 10,
    ) -> tuple[RetrievedChunk, ...]:
        """Return only chunks selected by the SQL entitlement match."""
        validated_query = _validate_query(query)
        if not isinstance(access_scope, AccessScope):
            raise TypeError("access_scope must be an AccessScope")
        if type(limit) is not int or not 1 <= limit <= _MAX_LIMIT:
            raise ValueError(f"limit must be an integer from 1 to {_MAX_LIMIT}")

        try:
            with self._lock:
                rows = self._connection.execute(
                    _RETRIEVE_SQL,
                    (
                        access_scope.user_id,
                        access_scope.role_id,
                        access_scope.client_id,
                        access_scope.matter_id,
                        access_scope.workflow_id,
                        validated_query,
                        limit,
                    ),
                ).fetchall()
        except sqlite3.OperationalError as error:
            if _is_fts5_query_error(error, validated_query):
                raise ValueError("query is not valid FTS5 syntax") from error
            raise
        return tuple(
            RetrievedChunk(
                source_id=SourceId(row[0]),
                source_version=row[1],
                chunk_id=ChunkId(row[2]),
                ordinal=row[3],
                title=row[4],
                text=row[5],
            )
            for row in rows
        )


__all__ = ["SQLiteFtsRetrievalProvider"]
