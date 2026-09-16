"""Local SQLite/FTS5 retrieval with SQL-enforced exact entitlements."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from threading import RLock

from privilab.domain.retrieval import (
    AccessScope,
    ChunkId,
    RetrievalSource,
    RetrievedChunk,
    SourceId,
)

_MAX_LIMIT = 100
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

_REQUIRED_SCHEMA_SIGNATURES = {
    "sources": (
        ("source_id", "TEXT", 0, 1),
        ("source_version", "TEXT", 1, 0),
        ("title", "TEXT", 1, 0),
    ),
    "source_entitlements": (
        ("source_id", "TEXT", 1, 0),
        ("user_id", "TEXT", 1, 0),
        ("role_id", "TEXT", 1, 0),
        ("client_id", "TEXT", 1, 0),
        ("matter_id", "TEXT", 1, 0),
        ("workflow_id", "TEXT", 1, 0),
    ),
    "chunks": (
        ("chunk_id", "TEXT", 0, 1),
        ("source_id", "TEXT", 1, 0),
        ("ordinal", "INTEGER", 1, 0),
        ("text", "TEXT", 1, 0),
    ),
    "chunks_fts": (
        ("chunk_id", "", 0, 0),
        ("text", "", 0, 0),
    ),
}
_ForeignKeySignature = tuple[str, str, str, str, str, str]
_REQUIRED_FOREIGN_KEYS: dict[str, tuple[_ForeignKeySignature, ...]] = {
    "sources": (),
    "source_entitlements": (
        ("sources", "source_id", "source_id", "NO ACTION", "NO ACTION", "NONE"),
    ),
    "chunks": (
        ("sources", "source_id", "source_id", "NO ACTION", "NO ACTION", "NONE"),
    ),
    "chunks_fts": (),
}
_REQUIRED_UNIQUE_COLUMNS: dict[str, tuple[tuple[str, ...], ...]] = {
    "sources": (),
    "source_entitlements": (
        (
            "source_id",
            "user_id",
            "role_id",
            "client_id",
            "matter_id",
            "workflow_id",
        ),
    ),
    "chunks": (("source_id", "ordinal"),),
    "chunks_fts": (),
}
_REQUIRED_FTS_DEFINITION = (
    "createvirtualtablechunks_ftsusingfts5(chunk_idunindexed,text)"
)
_BINARY_IDENTITY_DECLARATIONS = {
    "sources": {"source_id": "source_id TEXT PRIMARY KEY"},
    "source_entitlements": {
        "source_id": "source_id TEXT NOT NULL REFERENCES sources(source_id)",
        **{
            name: f"{name} TEXT NOT NULL"
            for name in ("user_id", "role_id", "client_id", "matter_id", "workflow_id")
        },
    },
    "chunks": {
        "chunk_id": "chunk_id TEXT PRIMARY KEY",
        "source_id": "source_id TEXT NOT NULL REFERENCES sources(source_id)",
    },
}
_GOVERNED_SCHEMA_NAMES = (
    *_REQUIRED_SCHEMA_SIGNATURES,
    *(
        f"chunks_fts_{suffix}"
        for suffix in ("data", "idx", "content", "docsize", "config")
    ),
)
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


def _schema_signature(
    connection: sqlite3.Connection,
    table: str,
) -> tuple[tuple[str, str, int, int], ...]:
    rows = connection.execute(
        f"PRAGMA table_info({_quote_identifier(table)})"
    ).fetchall()
    return tuple((row[1], row[2].upper(), row[3], row[5]) for row in rows)


def _foreign_key_signature(
    connection: sqlite3.Connection,
    table: str,
) -> tuple[_ForeignKeySignature, ...]:
    rows = connection.execute(
        f"PRAGMA foreign_key_list({_quote_identifier(table)})"
    ).fetchall()
    return tuple(
        sorted((row[2], row[3], row[4], row[5], row[6], row[7]) for row in rows)
    )


def _unique_constraint_columns(
    connection: sqlite3.Connection,
    table: str,
) -> tuple[tuple[str, ...], ...] | None:
    indexes = connection.execute(
        f"PRAGMA index_list({_quote_identifier(table)})"
    ).fetchall()
    signatures: list[tuple[str, ...]] = []
    for index in indexes:
        if index[2] != 1 or index[3] == "pk":
            continue
        if index[4] != 0:
            return None
        index_rows = connection.execute(
            f"PRAGMA index_xinfo({_quote_identifier(index[1])})"
        ).fetchall()
        columns: list[str] = []
        for row in index_rows:
            if row[5] != 1:
                continue
            if not isinstance(row[2], str) or row[3] != 0 or row[4] != "BINARY":
                return None
            columns.append(row[2])
        signatures.append(tuple(columns))
    return tuple(sorted(signatures))


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


def _has_binary_identity_columns(connection: sqlite3.Connection) -> bool:
    """Recognize only unambiguous governed column declarations, not arbitrary SQL.

    UNIQUE index collations do not establish the columns' comparison semantics.
    Read the authoritative declarations, allowing one explicit BINARY clause
    or SQLite's default BINARY. Quoting, comments and other syntax fail closed.
    """
    for table, required in _BINARY_IDENTITY_DECLARATIONS.items():
        definition = _schema_definition(connection, table)
        if (
            definition is None
            or re.fullmatch(r"[\w\s(),>=]+", definition, re.ASCII) is None
        ):
            return False
        match = re.fullmatch(
            rf"CREATE\s+TABLE\s+{table}\s*\((.*)\)",
            definition,
            re.IGNORECASE | re.ASCII | re.DOTALL,
        )
        if match is None:
            return False
        # Split only top-level declarations; REFERENCES/UNIQUE/CHECK use commas
        # and parentheses too. No quoted strings or comments can hide delimiters.
        declarations = []
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
                return False
        if depth != 0:
            return False
        declarations.append(body[start:].strip())
        for column, expected in required.items():
            candidates = [
                clause
                for clause in declarations
                if re.match(rf"{column}\s", clause, re.IGNORECASE | re.ASCII)
            ]
            if len(candidates) != 1:
                return False
            clause = re.sub(
                r"\bCOLLATE\s+BINARY\b",
                "",
                candidates[0],
                count=1,
                flags=re.IGNORECASE | re.ASCII,
            )
            if _normalize_schema_definition(clause) != _normalize_schema_definition(
                expected
            ):
                return False
    return True


def _has_required_ordinal_check(connection: sqlite3.Connection) -> bool:
    definition = _schema_definition(connection, "chunks")
    if definition is None or any(
        marker in definition for marker in ("--", "/*", "*/", "'", '"', "`", "[")
    ):
        return False
    normalized = _normalize_schema_definition(definition)
    return normalized.startswith("createtablechunks(") and re.findall(
        r"check\(([^()]*)\)", normalized
    ) == ["ordinal>=0"]


def _has_required_fts_definition(connection: sqlite3.Connection) -> bool:
    definition = _schema_definition(connection, "chunks_fts")
    return (
        definition is not None
        and _normalize_schema_definition(definition) == _REQUIRED_FTS_DEFINITION
    )


def _validate_schema_compatibility(connection: sqlite3.Connection) -> None:
    try:
        for table, expected_signature in _REQUIRED_SCHEMA_SIGNATURES.items():
            if (
                _schema_definition(connection, table) is None
                or _schema_signature(connection, table) != expected_signature
            ):
                raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
        for table, expected_foreign_keys in _REQUIRED_FOREIGN_KEYS.items():
            if _foreign_key_signature(connection, table) != expected_foreign_keys:
                raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
        for table, expected_columns in _REQUIRED_UNIQUE_COLUMNS.items():
            if _unique_constraint_columns(connection, table) != expected_columns:
                raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
        if not _has_required_ordinal_check(connection):
            raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
        if not _has_required_fts_definition(connection):
            raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
        if not _has_binary_identity_columns(connection):
            raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
        connection.execute(
            """
            SELECT rowid
            FROM chunks_fts
            WHERE chunks_fts MATCH ?
            LIMIT 0
            """,
            ("schema-compatibility-check",),
        ).fetchall()
    except sqlite3.DatabaseError as error:
        raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE) from error


def _has_existing_retrieval_schema(connection: sqlite3.Connection) -> bool:
    placeholders = ", ".join("?" for _ in _GOVERNED_SCHEMA_NAMES)
    try:
        row = connection.execute(
            f"""
            SELECT 1
            FROM sqlite_schema
            WHERE name COLLATE NOCASE IN ({placeholders})
            LIMIT 1
            """,
            _GOVERNED_SCHEMA_NAMES,
        ).fetchone()
    except sqlite3.DatabaseError as error:
        raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE) from error
    return row is not None


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
                if _has_existing_retrieval_schema(self._connection):
                    _validate_schema_compatibility(self._connection)
                self._connection.executescript(_SCHEMA)
                _validate_schema_compatibility(self._connection)
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
