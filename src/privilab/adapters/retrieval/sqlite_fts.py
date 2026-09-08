"""Local SQLite/FTS5 retrieval with SQL-enforced exact entitlements."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from privilab.domain.retrieval import (
    AccessScope,
    ChunkId,
    RetrievalSource,
    RetrievedChunk,
    SourceId,
)

_MAX_LIMIT = 100

_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
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

_QUERY_TERM_PATTERN = re.compile(r"[A-Za-z0-9_]+")

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
           authorized_chunks.ordinal
    FROM chunks_fts
    JOIN authorized_chunks ON authorized_chunks.chunk_id = chunks_fts.chunk_id
    WHERE chunks_fts MATCH ?
), query_terms(term) AS (
    VALUES {query_term_values}
), term_document_frequency AS (
    SELECT query_terms.term, COUNT(authorized_chunks.chunk_id) AS document_count
    FROM query_terms
    LEFT JOIN authorized_chunks
      ON instr(lower(authorized_chunks.text), lower(query_terms.term)) > 0
    GROUP BY query_terms.term
), scored_matches AS (
    SELECT authorized_matches.source_id, authorized_matches.chunk_id,
           authorized_matches.ordinal,
           SUM(
               (
                   length(lower(authorized_chunks.text))
                   - length(
                       replace(
                           lower(authorized_chunks.text),
                           lower(query_terms.term),
                           ""
                       )
                   )
               ) / length(query_terms.term) * 1.0
               / term_document_frequency.document_count
           ) AS score
    FROM authorized_matches
    JOIN authorized_chunks
      ON authorized_chunks.chunk_id = authorized_matches.chunk_id
    JOIN query_terms
      ON instr(lower(authorized_chunks.text), lower(query_terms.term)) > 0
    JOIN term_document_frequency
      ON term_document_frequency.term = query_terms.term
    GROUP BY authorized_matches.source_id, authorized_matches.chunk_id,
             authorized_matches.ordinal
)
SELECT scored_matches.source_id,
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


class SQLiteFtsRetrievalProvider:
    """Trusted local index administration plus authorization-scoped retrieval."""

    def __init__(self, database_path: str | Path) -> None:
        if not isinstance(database_path, (str, Path)):
            raise TypeError("database_path must be a string or Path")
        self._connection = sqlite3.connect(str(database_path))
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(_SCHEMA)

    def close(self) -> None:
        """Close the provider's local database connection."""
        self._connection.close()

    def index_source(self, source: RetrievalSource) -> None:
        """Atomically index trusted source metadata, chunks, and entitlements."""
        if not isinstance(source, RetrievalSource):
            raise TypeError("source must be a RetrievalSource")
        with self._connection:
            self._connection.execute(
                "INSERT INTO sources (source_id, title) VALUES (?, ?)",
                (source.source_id.value, source.title),
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
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        if not query or query != query.strip():
            raise ValueError("query must be a non-empty, trimmed string")
        if not isinstance(access_scope, AccessScope):
            raise TypeError("access_scope must be an AccessScope")
        if type(limit) is not int or not 1 <= limit <= _MAX_LIMIT:
            raise ValueError(f"limit must be an integer from 1 to {_MAX_LIMIT}")
        query_terms = tuple(
            sorted({term.lower() for term in _QUERY_TERM_PATTERN.findall(query)})
        )
        if not query_terms:
            raise ValueError("query must contain at least one searchable term")
        query_term_values = ", ".join("(?)" for _ in query_terms)
        retrieve_sql = _RETRIEVE_SQL.format(query_term_values=query_term_values)

        try:
            rows = self._connection.execute(
                retrieve_sql,
                (
                    access_scope.user_id,
                    access_scope.role_id,
                    access_scope.client_id,
                    access_scope.matter_id,
                    access_scope.workflow_id,
                    query,
                    *query_terms,
                    limit,
                ),
            ).fetchall()
        except sqlite3.OperationalError as error:
            raise ValueError("query is not valid FTS5 syntax") from error
        return tuple(
            RetrievedChunk(
                source_id=SourceId(row[0]),
                chunk_id=ChunkId(row[1]),
                ordinal=row[2],
                title=row[3],
                text=row[4],
            )
            for row in rows
        )


__all__ = ["SQLiteFtsRetrievalProvider"]
