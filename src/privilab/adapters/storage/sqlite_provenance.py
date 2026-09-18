"""Append-only SQLite persistence for application-authored run provenance."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from functools import cache
from pathlib import Path
from threading import RLock
from typing import NamedTuple, cast

from privilab.application.provenance import (
    ChunkProvenance,
    ContextProvenance,
    FailureStage,
    PermissionProvenance,
    PermissionStopReason,
    RunConfiguration,
    RunId,
    RunProvenance,
    RunStatus,
    SourceProvenance,
)
from privilab.domain import PermissionState

_PYTHON_STRIP_CHARACTERS_SQL = (
    "char(9, 10, 11, 12, 13, 28, 29, 30, 31, 32, 133, 160, 5760, "
    "8192, 8193, 8194, 8195, 8196, 8197, 8198, 8199, 8200, 8201, "
    "8202, 8232, 8233, 8239, 8287, 12288)"
)

_TABLE_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('PERMISSION_STOPPED', 'GENERATED', 'FAILED')
    ),
    stop_reason TEXT CHECK (
        stop_reason IS NULL OR stop_reason IN (
            'BLOCK', 'UNKNOWN', 'UNRESOLVED_CONDITIONS'
        )
    ),
    failure_stage TEXT CHECK (
        failure_stage IS NULL OR failure_stage IN (
            'PERMISSION', 'AUTHORIZATION', 'RETRIEVAL', 'MODEL'
        )
    ),
    synthetic_context INTEGER NOT NULL CHECK (synthetic_context = 1),
    user_id TEXT,
    role_id TEXT,
    client_id TEXT,
    matter_id TEXT,
    workflow_id TEXT,
    policy_id TEXT,
    policy_version TEXT,
    policy_schema_version INTEGER,
    permission_state TEXT CHECK (
        permission_state IS NULL OR permission_state IN (
            'ALLOW', 'CONDITIONAL', 'BLOCK', 'UNKNOWN'
        )
    ),
    configuration_hash TEXT NOT NULL,
    retrieval_called INTEGER NOT NULL CHECK (retrieval_called IN (0, 1)),
    model_called INTEGER NOT NULL CHECK (model_called IN (0, 1)),
    is_finalized INTEGER NOT NULL CHECK (is_finalized IN (0, 1)),
    CHECK (model_called = 0 OR retrieval_called = 1),
    CHECK (retrieval_called = 0 OR permission_state IS 'ALLOW'),
    CHECK (
        (
            permission_state IS NULL
            AND policy_id IS NULL
            AND policy_version IS NULL
            AND policy_schema_version IS NULL
        )
        OR (
            permission_state IS NOT NULL
            AND policy_id IS NOT NULL
            AND policy_version IS NOT NULL
            AND policy_schema_version IS NOT NULL
        )
    ),
    CHECK (
        (
            status IS 'PERMISSION_STOPPED'
            AND permission_state IS NOT NULL
            AND stop_reason IS NOT NULL
            AND failure_stage IS NULL
            AND retrieval_called = 0
            AND model_called = 0
            AND (
                (
                    permission_state IS 'BLOCK'
                    AND stop_reason IS 'BLOCK'
                )
                OR (
                    permission_state IS 'UNKNOWN'
                    AND stop_reason IS 'UNKNOWN'
                )
                OR (
                    permission_state IS 'CONDITIONAL'
                    AND stop_reason IS 'UNRESOLVED_CONDITIONS'
                )
            )
        )
        OR (
            status IS 'GENERATED'
            AND permission_state IS 'ALLOW'
            AND stop_reason IS NULL
            AND failure_stage IS NULL
            AND retrieval_called = 1
            AND model_called = 1
        )
        OR (
            status IS 'FAILED'
            AND stop_reason IS NULL
            AND failure_stage IS NOT NULL
            AND (
                (
                    failure_stage IS 'PERMISSION'
                    AND retrieval_called = 0
                    AND model_called = 0
                )
                OR (
                    failure_stage IS 'AUTHORIZATION'
                    AND retrieval_called = 0
                    AND model_called = 0
                )
                OR (
                    failure_stage IS 'RETRIEVAL'
                    AND retrieval_called = 1
                    AND model_called = 0
                )
                OR (
                    failure_stage IS 'MODEL'
                    AND retrieval_called = 1
                    AND model_called = 1
                )
            )
        )
    )
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS run_configurations (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    configuration_id TEXT NOT NULL,
    configuration_version TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    provider_version TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    model_content_hash TEXT,
    retrieval_provider_id TEXT NOT NULL,
    retrieval_provider_version TEXT NOT NULL,
    retrieval_limit INTEGER NOT NULL CHECK (retrieval_limit BETWEEN 1 AND 100),
    options_json TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS run_permission_conditions (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    condition_id TEXT NOT NULL,
    PRIMARY KEY (run_id, condition_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS run_sources (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    source_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    PRIMARY KEY (run_id, source_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS run_chunks (
    run_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    retrieval_position INTEGER NOT NULL CHECK (retrieval_position >= 0),
    PRIMARY KEY (run_id, chunk_id),
    UNIQUE (run_id, retrieval_position),
    FOREIGN KEY (run_id, source_id)
        REFERENCES run_sources(run_id, source_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS model_executions (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    provider_id TEXT NOT NULL,
    provider_version TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    model_content_hash TEXT
) WITHOUT ROWID;
"""

_SCHEMA = (
    _TABLE_SCHEMA
    + f"""
CREATE TRIGGER IF NOT EXISTS prevent_run_id_update
BEFORE UPDATE OF run_id ON runs
BEGIN
    SELECT RAISE(ABORT, 'run_id is immutable');
END;

CREATE TRIGGER IF NOT EXISTS runs_must_start_open
BEFORE INSERT ON runs
WHEN NEW.is_finalized != 0
BEGIN
    SELECT RAISE(ABORT, 'run must be inserted before finalization');
END;

CREATE TRIGGER IF NOT EXISTS finalized_run_requires_complete_provenance
BEFORE UPDATE OF is_finalized ON runs
WHEN OLD.is_finalized = 0 AND NEW.is_finalized = 1 AND (
    (
        NEW.status IS 'FAILED'
        AND (
            (NEW.failure_stage IS 'PERMISSION' AND NEW.permission_state IS NOT NULL)
            OR (
                NEW.failure_stage IS 'AUTHORIZATION'
                AND NEW.permission_state IS NOT 'ALLOW'
            )
        )
    )
    OR NOT EXISTS (
        SELECT 1 FROM run_configurations
        WHERE run_id = NEW.run_id
    )
    OR EXISTS (
        WITH RECURSIVE
        reconstruction_text(bytes) AS (
            SELECT CAST(
                CAST(NEW.run_id AS BLOB)
                || x'00' || CAST(NEW.started_at AS BLOB)
                || x'00' || CAST(NEW.completed_at AS BLOB)
                || x'00' || CAST(NEW.status AS BLOB)
                || x'00' || coalesce(CAST(NEW.stop_reason AS BLOB), x'')
                || x'00' || coalesce(CAST(NEW.failure_stage AS BLOB), x'')
                || x'00' || coalesce(CAST(NEW.user_id AS BLOB), x'')
                || x'00' || coalesce(CAST(NEW.role_id AS BLOB), x'')
                || x'00' || coalesce(CAST(NEW.client_id AS BLOB), x'')
                || x'00' || coalesce(CAST(NEW.matter_id AS BLOB), x'')
                || x'00' || coalesce(CAST(NEW.workflow_id AS BLOB), x'')
                || x'00' || coalesce(CAST(NEW.policy_id AS BLOB), x'')
                || x'00' || coalesce(CAST(NEW.policy_version AS BLOB), x'')
                || x'00' || coalesce(CAST(NEW.permission_state AS BLOB), x'')
                || x'00' || CAST(NEW.configuration_hash AS BLOB)
                AS BLOB
            )
            UNION ALL
            SELECT CAST(
                CAST(run_id AS BLOB)
                || x'00' || CAST(configuration_id AS BLOB)
                || x'00' || CAST(configuration_version AS BLOB)
                || x'00' || CAST(provider_id AS BLOB)
                || x'00' || CAST(provider_version AS BLOB)
                || x'00' || CAST(model_id AS BLOB)
                || x'00' || CAST(model_version AS BLOB)
                || x'00' || coalesce(CAST(model_content_hash AS BLOB), x'')
                || x'00' || CAST(retrieval_provider_id AS BLOB)
                || x'00' || CAST(retrieval_provider_version AS BLOB)
                || x'00' || CAST(options_json AS BLOB)
                AS BLOB
            )
            FROM run_configurations
            WHERE run_id IS NEW.run_id
            UNION ALL
            SELECT CAST(
                CAST(run_id AS BLOB)
                || x'00' || CAST(condition_id AS BLOB)
                AS BLOB
            )
            FROM run_permission_conditions
            WHERE run_id IS NEW.run_id
            UNION ALL
            SELECT CAST(
                CAST(run_id AS BLOB)
                || x'00' || CAST(source_id AS BLOB)
                || x'00' || CAST(source_version AS BLOB)
                AS BLOB
            )
            FROM run_sources
            WHERE run_id IS NEW.run_id
            UNION ALL
            SELECT CAST(
                CAST(run_id AS BLOB)
                || x'00' || CAST(source_id AS BLOB)
                || x'00' || CAST(chunk_id AS BLOB)
                AS BLOB
            )
            FROM run_chunks
            WHERE run_id IS NEW.run_id
            UNION ALL
            SELECT CAST(
                CAST(run_id AS BLOB)
                || x'00' || CAST(provider_id AS BLOB)
                || x'00' || CAST(provider_version AS BLOB)
                || x'00' || CAST(model_id AS BLOB)
                || x'00' || CAST(model_version AS BLOB)
                || x'00' || coalesce(CAST(model_content_hash AS BLOB), x'')
                AS BLOB
            )
            FROM model_executions
            WHERE run_id IS NEW.run_id
        ),
        valid_utf8(bytes, position) AS (
            SELECT bytes, 1
            FROM reconstruction_text
            UNION ALL
            SELECT bytes,
                   CASE
                       WHEN hex(substr(bytes, position, 1))
                            BETWEEN '00' AND '7F'
                           THEN position + 1
                       WHEN hex(substr(bytes, position, 1))
                            BETWEEN 'C2' AND 'DF'
                            AND hex(substr(bytes, position + 1, 1))
                                BETWEEN '80' AND 'BF'
                           THEN position + 2
                       WHEN hex(substr(bytes, position, 1)) = 'E0'
                            AND hex(substr(bytes, position + 1, 1))
                                BETWEEN 'A0' AND 'BF'
                            AND hex(substr(bytes, position + 2, 1))
                                BETWEEN '80' AND 'BF'
                           THEN position + 3
                       WHEN hex(substr(bytes, position, 1))
                            BETWEEN 'E1' AND 'EC'
                            AND hex(substr(bytes, position + 1, 1))
                                BETWEEN '80' AND 'BF'
                            AND hex(substr(bytes, position + 2, 1))
                                BETWEEN '80' AND 'BF'
                           THEN position + 3
                       WHEN hex(substr(bytes, position, 1)) = 'ED'
                            AND hex(substr(bytes, position + 1, 1))
                                BETWEEN '80' AND '9F'
                            AND hex(substr(bytes, position + 2, 1))
                                BETWEEN '80' AND 'BF'
                           THEN position + 3
                       WHEN hex(substr(bytes, position, 1))
                            BETWEEN 'EE' AND 'EF'
                            AND hex(substr(bytes, position + 1, 1))
                                BETWEEN '80' AND 'BF'
                            AND hex(substr(bytes, position + 2, 1))
                                BETWEEN '80' AND 'BF'
                           THEN position + 3
                       WHEN hex(substr(bytes, position, 1)) = 'F0'
                            AND hex(substr(bytes, position + 1, 1))
                                BETWEEN '90' AND 'BF'
                            AND hex(substr(bytes, position + 2, 1))
                                BETWEEN '80' AND 'BF'
                            AND hex(substr(bytes, position + 3, 1))
                                BETWEEN '80' AND 'BF'
                           THEN position + 4
                       WHEN hex(substr(bytes, position, 1))
                            BETWEEN 'F1' AND 'F3'
                            AND hex(substr(bytes, position + 1, 1))
                                BETWEEN '80' AND 'BF'
                            AND hex(substr(bytes, position + 2, 1))
                                BETWEEN '80' AND 'BF'
                            AND hex(substr(bytes, position + 3, 1))
                                BETWEEN '80' AND 'BF'
                           THEN position + 4
                       WHEN hex(substr(bytes, position, 1)) = 'F4'
                            AND hex(substr(bytes, position + 1, 1))
                                BETWEEN '80' AND '8F'
                            AND hex(substr(bytes, position + 2, 1))
                                BETWEEN '80' AND 'BF'
                            AND hex(substr(bytes, position + 3, 1))
                                BETWEEN '80' AND 'BF'
                           THEN position + 4
                       ELSE 0
                   END
            FROM valid_utf8
            WHERE position > 0 AND position <= length(bytes)
        )
        SELECT 1
        FROM valid_utf8
        WHERE position = 0
    )
    OR typeof(NEW.run_id) != 'text'
    OR NEW.run_id = ''
    OR NEW.run_id != trim(NEW.run_id, {_PYTHON_STRIP_CHARACTERS_SQL})
    OR typeof(NEW.started_at) != 'text'
    OR instr(CAST(NEW.started_at AS BLOB), x'00') != 0
    OR length(CAST(NEW.started_at AS BLOB)) NOT IN (27, 32)
    OR length(NEW.started_at) NOT IN (27, 32)
    OR substr(NEW.started_at, 1, 26) NOT GLOB
       '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]'
    OR CAST(substr(NEW.started_at, 1, 4) AS INTEGER) NOT BETWEEN 1 AND 9999
    OR CAST(substr(NEW.started_at, 6, 2) AS INTEGER) NOT BETWEEN 1 AND 12
    OR CAST(substr(NEW.started_at, 9, 2) AS INTEGER) < 1
    OR CAST(substr(NEW.started_at, 9, 2) AS INTEGER) >
       CASE
           WHEN CAST(substr(NEW.started_at, 6, 2) AS INTEGER) = 2
               THEN CASE
                   WHEN CAST(substr(NEW.started_at, 1, 4) AS INTEGER) % 4 = 0
                        AND (
                            CAST(substr(NEW.started_at, 1, 4) AS INTEGER) % 100 != 0
                            OR CAST(substr(NEW.started_at, 1, 4) AS INTEGER) % 400 = 0
                        )
                       THEN 29
                   ELSE 28
               END
           WHEN CAST(substr(NEW.started_at, 6, 2) AS INTEGER)
                IN (4, 6, 9, 11)
               THEN 30
           ELSE 31
       END
    OR CAST(substr(NEW.started_at, 12, 2) AS INTEGER) > 23
    OR CAST(substr(NEW.started_at, 15, 2) AS INTEGER) > 59
    OR CAST(substr(NEW.started_at, 18, 2) AS INTEGER) > 59
    OR (
        NOT (
            length(NEW.started_at) = 27
            AND substr(NEW.started_at, 27, 1) = 'Z'
        )
        AND NOT (
            length(NEW.started_at) = 32
            AND substr(NEW.started_at, 27, 1) IN ('+', '-')
            AND substr(NEW.started_at, 28, 2) GLOB '[0-9][0-9]'
            AND CAST(substr(NEW.started_at, 28, 2) AS INTEGER) <= 23
            AND substr(NEW.started_at, 30, 1) = ':'
            AND substr(NEW.started_at, 31, 2) GLOB '[0-9][0-9]'
            AND CAST(substr(NEW.started_at, 31, 2) AS INTEGER) <= 59
        )
    )
    OR typeof(NEW.completed_at) != 'text'
    OR instr(CAST(NEW.completed_at AS BLOB), x'00') != 0
    OR length(CAST(NEW.completed_at AS BLOB)) NOT IN (27, 32)
    OR length(NEW.completed_at) NOT IN (27, 32)
    OR substr(NEW.completed_at, 1, 26) NOT GLOB
       '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]'
    OR CAST(substr(NEW.completed_at, 1, 4) AS INTEGER) NOT BETWEEN 1 AND 9999
    OR CAST(substr(NEW.completed_at, 6, 2) AS INTEGER) NOT BETWEEN 1 AND 12
    OR CAST(substr(NEW.completed_at, 9, 2) AS INTEGER) < 1
    OR CAST(substr(NEW.completed_at, 9, 2) AS INTEGER) >
       CASE
           WHEN CAST(substr(NEW.completed_at, 6, 2) AS INTEGER) = 2
               THEN CASE
                   WHEN CAST(substr(NEW.completed_at, 1, 4) AS INTEGER) % 4 = 0
                        AND (
                            CAST(substr(NEW.completed_at, 1, 4) AS INTEGER) % 100 != 0
                            OR CAST(substr(NEW.completed_at, 1, 4) AS INTEGER) % 400 = 0
                        )
                       THEN 29
                   ELSE 28
               END
           WHEN CAST(substr(NEW.completed_at, 6, 2) AS INTEGER)
                IN (4, 6, 9, 11)
               THEN 30
           ELSE 31
       END
    OR CAST(substr(NEW.completed_at, 12, 2) AS INTEGER) > 23
    OR CAST(substr(NEW.completed_at, 15, 2) AS INTEGER) > 59
    OR CAST(substr(NEW.completed_at, 18, 2) AS INTEGER) > 59
    OR (
        NOT (
            length(NEW.completed_at) = 27
            AND substr(NEW.completed_at, 27, 1) = 'Z'
        )
        AND NOT (
            length(NEW.completed_at) = 32
            AND substr(NEW.completed_at, 27, 1) IN ('+', '-')
            AND substr(NEW.completed_at, 28, 2) GLOB '[0-9][0-9]'
            AND CAST(substr(NEW.completed_at, 28, 2) AS INTEGER) <= 23
            AND substr(NEW.completed_at, 30, 1) = ':'
            AND substr(NEW.completed_at, 31, 2) GLOB '[0-9][0-9]'
            AND CAST(substr(NEW.completed_at, 31, 2) AS INTEGER) <= 59
        )
    )
    OR EXISTS (
        WITH
        timestamp_values(kind, value) AS (
            SELECT 'started', NEW.started_at
            UNION ALL
            SELECT 'completed', NEW.completed_at
        ),
        timestamp_components AS (
            SELECT
                kind,
                CAST(substr(value, 1, 4) AS INTEGER) AS year,
                CAST(substr(value, 6, 2) AS INTEGER) AS month,
                CAST(substr(value, 9, 2) AS INTEGER) AS day,
                CAST(substr(value, 12, 2) AS INTEGER) AS hour,
                CAST(substr(value, 15, 2) AS INTEGER) AS minute,
                CAST(substr(value, 18, 2) AS INTEGER) AS second,
                CAST(substr(value, 21, 6) AS INTEGER) AS microsecond,
                CASE
                    WHEN length(value) = 27 THEN 0
                    ELSE (
                        CASE substr(value, 27, 1)
                            WHEN '+' THEN 1
                            ELSE -1
                        END
                        * (
                            CAST(substr(value, 28, 2) AS INTEGER) * 60
                            + CAST(substr(value, 31, 2) AS INTEGER)
                        )
                    )
                END AS offset_minutes
            FROM timestamp_values
        ),
        exact_instants AS (
            SELECT
                kind,
                (
                    365 * (year - 1)
                    + (year - 1) / 4
                    - (year - 1) / 100
                    + (year - 1) / 400
                    + CASE month
                        WHEN 1 THEN 0
                        WHEN 2 THEN 31
                        WHEN 3 THEN 59
                        WHEN 4 THEN 90
                        WHEN 5 THEN 120
                        WHEN 6 THEN 151
                        WHEN 7 THEN 181
                        WHEN 8 THEN 212
                        WHEN 9 THEN 243
                        WHEN 10 THEN 273
                        WHEN 11 THEN 304
                        WHEN 12 THEN 334
                      END
                    + day - 1
                    + CASE
                        WHEN month > 2
                             AND year % 4 = 0
                             AND (year % 100 != 0 OR year % 400 = 0)
                            THEN 1
                        ELSE 0
                      END
                ) * 86400000000
                + hour * 3600000000
                + minute * 60000000
                + second * 1000000
                + microsecond
                - offset_minutes * 60000000 AS instant
            FROM timestamp_components
        )
        SELECT 1
        FROM exact_instants AS completed
        JOIN exact_instants AS started
          ON completed.kind = 'completed'
         AND started.kind = 'started'
        WHERE completed.instant < started.instant
           OR started.instant NOT BETWEEN 0 AND 315537897599999999
           OR completed.instant NOT BETWEEN 0 AND 315537897599999999
    )
    OR typeof(NEW.configuration_hash) != 'text'
    OR length(CAST(NEW.configuration_hash AS BLOB)) != 71
    OR instr(CAST(NEW.configuration_hash AS BLOB), x'00') != 0
    OR substr(CAST(NEW.configuration_hash AS BLOB), 1, 7) != x'7368613235363a'
    OR substr(NEW.configuration_hash, 8) GLOB '*[^0-9a-f]*'
    OR (
        NEW.user_id IS NOT NULL
        AND (
            typeof(NEW.user_id) != 'text'
            OR NEW.user_id = ''
            OR NEW.user_id != trim(
                NEW.user_id, {_PYTHON_STRIP_CHARACTERS_SQL}
            )
        )
    )
    OR (
        NEW.role_id IS NOT NULL
        AND (
            typeof(NEW.role_id) != 'text'
            OR NEW.role_id = ''
            OR NEW.role_id != trim(
                NEW.role_id, {_PYTHON_STRIP_CHARACTERS_SQL}
            )
        )
    )
    OR (
        NEW.client_id IS NOT NULL
        AND (
            typeof(NEW.client_id) != 'text'
            OR NEW.client_id = ''
            OR NEW.client_id != trim(
                NEW.client_id, {_PYTHON_STRIP_CHARACTERS_SQL}
            )
        )
    )
    OR (
        NEW.matter_id IS NOT NULL
        AND (
            typeof(NEW.matter_id) != 'text'
            OR NEW.matter_id = ''
            OR NEW.matter_id != trim(
                NEW.matter_id, {_PYTHON_STRIP_CHARACTERS_SQL}
            )
        )
    )
    OR (
        NEW.workflow_id IS NOT NULL
        AND (
            typeof(NEW.workflow_id) != 'text'
            OR NEW.workflow_id = ''
            OR NEW.workflow_id != trim(
                NEW.workflow_id, {_PYTHON_STRIP_CHARACTERS_SQL}
            )
        )
    )
    OR (
        NEW.policy_id IS NOT NULL
        AND (
            typeof(NEW.policy_id) != 'text'
            OR NEW.policy_id = ''
            OR NEW.policy_id != trim(
                NEW.policy_id, {_PYTHON_STRIP_CHARACTERS_SQL}
            )
        )
    )
    OR (
        NEW.policy_version IS NOT NULL
        AND (
            typeof(NEW.policy_version) != 'text'
            OR NEW.policy_version = ''
            OR NEW.policy_version != trim(
                NEW.policy_version, {_PYTHON_STRIP_CHARACTERS_SQL}
            )
        )
    )
    OR (
        NEW.policy_schema_version IS NOT NULL
        AND typeof(NEW.policy_schema_version) != 'integer'
    )
    OR EXISTS (
        SELECT 1
        FROM run_configurations AS configuration
        WHERE configuration.run_id = NEW.run_id
          AND (
              typeof(configuration.configuration_id) != 'text'
              OR configuration.configuration_id = ''
              OR configuration.configuration_id != trim(
                  configuration.configuration_id,
                  {_PYTHON_STRIP_CHARACTERS_SQL}
              )
              OR typeof(configuration.configuration_version) != 'text'
              OR configuration.configuration_version = ''
              OR configuration.configuration_version != trim(
                  configuration.configuration_version,
                  {_PYTHON_STRIP_CHARACTERS_SQL}
              )
              OR typeof(configuration.provider_id) != 'text'
              OR configuration.provider_id = ''
              OR configuration.provider_id != trim(
                  configuration.provider_id, {_PYTHON_STRIP_CHARACTERS_SQL}
              )
              OR typeof(configuration.provider_version) != 'text'
              OR configuration.provider_version = ''
              OR configuration.provider_version != trim(
                  configuration.provider_version,
                  {_PYTHON_STRIP_CHARACTERS_SQL}
              )
              OR typeof(configuration.model_id) != 'text'
              OR configuration.model_id = ''
              OR configuration.model_id != trim(
                  configuration.model_id, {_PYTHON_STRIP_CHARACTERS_SQL}
              )
              OR typeof(configuration.model_version) != 'text'
              OR configuration.model_version = ''
              OR configuration.model_version != trim(
                  configuration.model_version, {_PYTHON_STRIP_CHARACTERS_SQL}
              )
              OR typeof(configuration.retrieval_provider_id) != 'text'
              OR configuration.retrieval_provider_id = ''
              OR configuration.retrieval_provider_id != trim(
                  configuration.retrieval_provider_id,
                  {_PYTHON_STRIP_CHARACTERS_SQL}
              )
              OR typeof(configuration.retrieval_provider_version) != 'text'
              OR configuration.retrieval_provider_version = ''
              OR configuration.retrieval_provider_version != trim(
                  configuration.retrieval_provider_version,
                  {_PYTHON_STRIP_CHARACTERS_SQL}
              )
              OR typeof(configuration.retrieval_limit) != 'integer'
              OR (
                  configuration.model_content_hash IS NOT NULL
                  AND (
                      typeof(configuration.model_content_hash) != 'text'
                      OR length(CAST(configuration.model_content_hash AS BLOB)) != 71
                      OR instr(CAST(configuration.model_content_hash AS BLOB), x'00')
                         != 0
                      OR substr(CAST(configuration.model_content_hash AS BLOB), 1, 7)
                         != x'7368613235363a'
                      OR substr(configuration.model_content_hash, 8)
                         GLOB '*[^0-9a-f]*'
                  )
              )
              OR CASE
                  WHEN typeof(configuration.options_json) != 'text' THEN 1
                  WHEN json_valid(configuration.options_json) = 0 THEN 1
                  WHEN json_type(configuration.options_json) IS NOT 'object'
                      THEN 1
                  ELSE 0
                 END
              OR EXISTS (
                  SELECT 1
                  FROM json_each(
                      CASE
                          WHEN json_valid(configuration.options_json)
                              THEN configuration.options_json
                          ELSE '{{}}'
                      END
                  ) AS option
                  GROUP BY CAST(option.key AS BLOB)
                  HAVING count(*) > 1
              )
              OR EXISTS (
                  SELECT 1
                  FROM json_each(
                      CASE
                          WHEN json_valid(configuration.options_json)
                              THEN configuration.options_json
                          ELSE '{{}}'
                      END
                  ) AS option
                  WHERE option.type != 'text'
                     OR option.key = ''
                     OR option.key != trim(
                         option.key, {_PYTHON_STRIP_CHARACTERS_SQL}
                     )
                     OR option.value = ''
                     OR option.value != trim(
                         option.value, {_PYTHON_STRIP_CHARACTERS_SQL}
                     )
                     OR EXISTS (
                         WITH RECURSIVE
                         option_payload(bytes) AS (
                             SELECT CAST(
                                 CAST(option.key AS BLOB)
                                 || x'00'
                                 || CAST(option.value AS BLOB)
                                 AS BLOB
                             )
                         ),
                         byte_positions(position) AS (
                             SELECT 1
                             UNION ALL
                             SELECT position + 1
                             FROM byte_positions
                             WHERE position < length(
                                 (SELECT bytes FROM option_payload)
                             )
                         )
                         SELECT 1
                         FROM byte_positions
                         WHERE hex(substr(
                                   (SELECT bytes FROM option_payload),
                                   position,
                                   1
                               )) = 'ED'
                           AND substr(hex(substr(
                                   (SELECT bytes FROM option_payload),
                                   position + 1,
                                   1
                               )), 1, 1) IN ('A', 'B')
                           AND substr(hex(substr(
                                   (SELECT bytes FROM option_payload),
                                   position + 2,
                                   1
                               )), 1, 1) IN ('8', '9', 'A', 'B')
                     )
              )
          )
    )
    OR EXISTS (
        SELECT 1
        FROM run_permission_conditions AS condition
        WHERE condition.run_id = NEW.run_id
          AND (
              typeof(condition.condition_id) != 'text'
              OR condition.condition_id = ''
              OR condition.condition_id != trim(
                  condition.condition_id, {_PYTHON_STRIP_CHARACTERS_SQL}
              )
          )
    )
    OR EXISTS (
        SELECT 1
        FROM run_sources AS source
        WHERE source.run_id = NEW.run_id
          AND (
              typeof(source.source_id) != 'text'
              OR source.source_id = ''
              OR source.source_id != trim(
                  source.source_id, {_PYTHON_STRIP_CHARACTERS_SQL}
              )
              OR typeof(source.source_version) != 'text'
              OR source.source_version = ''
              OR source.source_version != trim(
                  source.source_version, {_PYTHON_STRIP_CHARACTERS_SQL}
              )
          )
    )
    OR EXISTS (
        SELECT 1
        FROM run_chunks AS chunk
        WHERE chunk.run_id = NEW.run_id
          AND (
              typeof(chunk.chunk_id) != 'text'
              OR chunk.chunk_id = ''
              OR chunk.chunk_id != trim(
                  chunk.chunk_id, {_PYTHON_STRIP_CHARACTERS_SQL}
              )
              OR typeof(chunk.ordinal) != 'integer'
              OR typeof(chunk.retrieval_position) != 'integer'
          )
    )
    OR EXISTS (
        SELECT 1
        FROM run_chunks AS chunk
        WHERE chunk.run_id = NEW.run_id
          AND NOT EXISTS (
              SELECT 1
              FROM run_sources AS source
              WHERE source.run_id = chunk.run_id
                AND source.source_id = chunk.source_id
          )
    )
    OR (
        NEW.permission_state IS 'CONDITIONAL'
        AND NOT EXISTS (
            SELECT 1 FROM run_permission_conditions
            WHERE run_id = NEW.run_id
        )
    )
    OR (
        NEW.permission_state IS NOT 'CONDITIONAL'
        AND EXISTS (
            SELECT 1 FROM run_permission_conditions
            WHERE run_id = NEW.run_id
        )
    )
    OR EXISTS (
        SELECT 1 FROM run_sources
        WHERE run_sources.run_id = NEW.run_id
          AND NOT EXISTS (
              SELECT 1 FROM run_chunks
              WHERE run_chunks.run_id = run_sources.run_id
                AND run_chunks.source_id = run_sources.source_id
          )
    )
    OR (
        NEW.retrieval_called = 0
        AND EXISTS (
            SELECT 1 FROM run_sources
            WHERE run_id = NEW.run_id
        )
    )
    OR (
        EXISTS (SELECT 1 FROM run_chunks WHERE run_id = NEW.run_id)
        AND (
            (SELECT min(retrieval_position) FROM run_chunks
             WHERE run_id = NEW.run_id) IS NOT 0
            OR (SELECT max(retrieval_position) FROM run_chunks
                WHERE run_id = NEW.run_id) IS NOT (
                    SELECT count(*) - 1 FROM run_chunks
                    WHERE run_id = NEW.run_id
                )
        )
    )
    OR EXISTS (
        SELECT 1 FROM model_executions AS execution
        WHERE execution.run_id = NEW.run_id
          AND execution.model_content_hash IS NOT NULL
          AND (
              typeof(execution.model_content_hash) != 'text'
              OR length(CAST(execution.model_content_hash AS BLOB)) != 71
              OR instr(CAST(execution.model_content_hash AS BLOB), x'00') != 0
              OR substr(CAST(execution.model_content_hash AS BLOB), 1, 7)
                 != x'7368613235363a'
              OR substr(execution.model_content_hash, 8) GLOB '*[^0-9a-f]*'
          )
    )
    OR (
        NEW.model_called = 0
        AND EXISTS (
            SELECT 1 FROM model_executions
            WHERE run_id = NEW.run_id
        )
    )
    OR (
        NEW.model_called = 1
        AND NOT EXISTS (
            SELECT 1
            FROM model_executions
            JOIN run_configurations USING (run_id)
            WHERE model_executions.run_id = NEW.run_id
              AND model_executions.provider_id
                  IS run_configurations.provider_id
              AND model_executions.provider_version
                  IS run_configurations.provider_version
              AND model_executions.model_id
                  IS run_configurations.model_id
              AND model_executions.model_version
                  IS run_configurations.model_version
              AND model_executions.model_content_hash
                  IS run_configurations.model_content_hash
        )
    )
)
BEGIN
    SELECT RAISE(ABORT, 'run provenance is incomplete');
END;

CREATE TRIGGER IF NOT EXISTS prevent_finalized_run_update
BEFORE UPDATE ON runs
WHEN OLD.is_finalized = 1
 AND NEW.run_id IS OLD.run_id
 AND (
    NEW.started_at IS NOT OLD.started_at
    OR NEW.completed_at IS NOT OLD.completed_at
    OR NEW.status IS NOT OLD.status
    OR NEW.stop_reason IS NOT OLD.stop_reason
    OR NEW.failure_stage IS NOT OLD.failure_stage
    OR NEW.synthetic_context IS NOT OLD.synthetic_context
    OR NEW.user_id IS NOT OLD.user_id
    OR NEW.role_id IS NOT OLD.role_id
    OR NEW.client_id IS NOT OLD.client_id
    OR NEW.matter_id IS NOT OLD.matter_id
    OR NEW.workflow_id IS NOT OLD.workflow_id
    OR NEW.policy_id IS NOT OLD.policy_id
    OR NEW.policy_version IS NOT OLD.policy_version
    OR NEW.policy_schema_version IS NOT OLD.policy_schema_version
    OR NEW.permission_state IS NOT OLD.permission_state
    OR NEW.configuration_hash IS NOT OLD.configuration_hash
    OR NEW.retrieval_called IS NOT OLD.retrieval_called
    OR NEW.model_called IS NOT OLD.model_called
    OR NEW.is_finalized IS NOT OLD.is_finalized
 )
BEGIN
    SELECT RAISE(ABORT, 'finalized run provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_finalized_run_delete
BEFORE DELETE ON runs
WHEN OLD.is_finalized = 1
BEGIN
    SELECT RAISE(ABORT, 'finalized run provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_finalized_run_replace
BEFORE INSERT ON runs
WHEN EXISTS (
    SELECT 1 FROM runs
    WHERE run_id = NEW.run_id AND is_finalized = 1
)
BEGIN
    SELECT RAISE(ABORT, 'finalized run provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_run_configurations_run_id_update
BEFORE UPDATE OF run_id ON run_configurations
BEGIN
    SELECT RAISE(ABORT, 'run_id is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_run_permission_conditions_run_id_update
BEFORE UPDATE OF run_id ON run_permission_conditions
BEGIN
    SELECT RAISE(ABORT, 'run_id is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_run_sources_run_id_update
BEFORE UPDATE OF run_id ON run_sources
BEGIN
    SELECT RAISE(ABORT, 'run_id is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_run_chunks_run_id_update
BEFORE UPDATE OF run_id ON run_chunks
BEGIN
    SELECT RAISE(ABORT, 'run_id is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_model_executions_run_id_update
BEFORE UPDATE OF run_id ON model_executions
BEGIN
    SELECT RAISE(ABORT, 'run_id is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_finalized_run_configurations_insert
BEFORE INSERT ON run_configurations
WHEN EXISTS (
    SELECT 1 FROM runs
    WHERE run_id = NEW.run_id AND is_finalized = 1
)
BEGIN
    SELECT RAISE(ABORT, 'finalized run provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_finalized_run_configurations_update
BEFORE UPDATE ON run_configurations
WHEN NEW.run_id IS OLD.run_id AND EXISTS (
    SELECT 1 FROM runs
    WHERE run_id = OLD.run_id AND is_finalized = 1
)
BEGIN
    SELECT RAISE(ABORT, 'finalized run provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_finalized_run_configurations_delete
BEFORE DELETE ON run_configurations
WHEN EXISTS (
    SELECT 1 FROM runs
    WHERE run_id = OLD.run_id AND is_finalized = 1
)
BEGIN
    SELECT RAISE(ABORT, 'finalized run provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_finalized_run_permission_conditions_insert
BEFORE INSERT ON run_permission_conditions
WHEN EXISTS (
    SELECT 1 FROM runs
    WHERE run_id = NEW.run_id AND is_finalized = 1
)
BEGIN
    SELECT RAISE(ABORT, 'finalized run provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_finalized_run_permission_conditions_update
BEFORE UPDATE ON run_permission_conditions
WHEN NEW.run_id IS OLD.run_id AND EXISTS (
    SELECT 1 FROM runs
    WHERE run_id = OLD.run_id AND is_finalized = 1
)
BEGIN
    SELECT RAISE(ABORT, 'finalized run provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_finalized_run_permission_conditions_delete
BEFORE DELETE ON run_permission_conditions
WHEN EXISTS (
    SELECT 1 FROM runs
    WHERE run_id = OLD.run_id AND is_finalized = 1
)
BEGIN
    SELECT RAISE(ABORT, 'finalized run provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_finalized_run_sources_insert
BEFORE INSERT ON run_sources
WHEN EXISTS (
    SELECT 1 FROM runs
    WHERE run_id = NEW.run_id AND is_finalized = 1
)
BEGIN
    SELECT RAISE(ABORT, 'finalized run provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_finalized_run_sources_update
BEFORE UPDATE ON run_sources
WHEN NEW.run_id IS OLD.run_id AND EXISTS (
    SELECT 1 FROM runs
    WHERE run_id = OLD.run_id AND is_finalized = 1
)
BEGIN
    SELECT RAISE(ABORT, 'finalized run provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_finalized_run_sources_delete
BEFORE DELETE ON run_sources
WHEN EXISTS (
    SELECT 1 FROM runs
    WHERE run_id = OLD.run_id AND is_finalized = 1
)
BEGIN
    SELECT RAISE(ABORT, 'finalized run provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_finalized_run_chunks_insert
BEFORE INSERT ON run_chunks
WHEN EXISTS (
    SELECT 1 FROM runs
    WHERE run_id = NEW.run_id AND is_finalized = 1
)
BEGIN
    SELECT RAISE(ABORT, 'finalized run provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_finalized_run_chunks_update
BEFORE UPDATE ON run_chunks
WHEN NEW.run_id IS OLD.run_id AND EXISTS (
    SELECT 1 FROM runs
    WHERE run_id = OLD.run_id AND is_finalized = 1
)
BEGIN
    SELECT RAISE(ABORT, 'finalized run provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_finalized_run_chunks_delete
BEFORE DELETE ON run_chunks
WHEN EXISTS (
    SELECT 1 FROM runs
    WHERE run_id = OLD.run_id AND is_finalized = 1
)
BEGIN
    SELECT RAISE(ABORT, 'finalized run provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_finalized_model_executions_insert
BEFORE INSERT ON model_executions
WHEN EXISTS (
    SELECT 1 FROM runs
    WHERE run_id = NEW.run_id AND is_finalized = 1
)
BEGIN
    SELECT RAISE(ABORT, 'finalized run provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_finalized_model_executions_update
BEFORE UPDATE ON model_executions
WHEN NEW.run_id IS OLD.run_id AND EXISTS (
    SELECT 1 FROM runs
    WHERE run_id = OLD.run_id AND is_finalized = 1
)
BEGIN
    SELECT RAISE(ABORT, 'finalized run provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS prevent_finalized_model_executions_delete
BEFORE DELETE ON model_executions
WHEN EXISTS (
    SELECT 1 FROM runs
    WHERE run_id = OLD.run_id AND is_finalized = 1
)
BEGIN
    SELECT RAISE(ABORT, 'finalized run provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS run_sources_require_retrieval
BEFORE INSERT ON run_sources
WHEN NOT EXISTS (
    SELECT 1 FROM runs
    WHERE run_id = NEW.run_id AND retrieval_called = 1
)
BEGIN
    SELECT RAISE(ABORT, 'source provenance requires completed retrieval');
END;

CREATE TRIGGER IF NOT EXISTS model_provenance_requires_execution
BEFORE INSERT ON model_executions
WHEN NOT EXISTS (
    SELECT 1 FROM runs
    WHERE run_id = NEW.run_id AND model_called = 1
)
BEGIN
    SELECT RAISE(ABORT, 'model provenance requires model execution');
END;
"""
)


_INCOMPATIBLE_SCHEMA_MESSAGE = (
    "local provenance schema is incompatible; a fresh database is required"
)


_SchemaObject = tuple[str, str, str, str]
_IndexColumn = tuple[int, int, str, int, str, int]
_IndexSignature = tuple[str, int, str, int, tuple[_IndexColumn, ...]]


class _SchemaCatalog(NamedTuple):
    objects: tuple[_SchemaObject, ...]
    unique_indexes: tuple[_IndexSignature, ...]


def _unique_indexes(
    connection: sqlite3.Connection, tables: tuple[str, ...]
) -> tuple[_IndexSignature, ...]:
    """Read conflict identities, keeping duplicates but not enumeration or names.

    Extra non-unique indexes cannot cause REPLACE to delete a conflicting row.
    Unique expression/partial indexes are never part of our trusted schema:
    reject them without interpreting any target-supplied SQL.
    """
    indexes: list[_IndexSignature] = []
    for table in tables:
        for unique, origin, partial, name in connection.execute(
            'SELECT "unique", origin, partial, name FROM pragma_index_list(?)',
            (table,),
        ):
            if (
                type(unique) is not int
                or unique not in (0, 1)
                or origin not in ("c", "u", "pk")
                or type(partial) is not int
                or partial not in (0, 1)
                or not isinstance(name, str)
                or not name
                or (unique == 0 and origin != "c")
            ):
                raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
            if not unique:
                continue
            if partial:
                raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
            columns: list[_IndexColumn] = []
            for seq, cid, column, descending, collation, key in connection.execute(
                'SELECT seqno, cid, name, "desc", coll, "key" '
                "FROM pragma_index_xinfo(?) ORDER BY seqno",
                (name,),
            ):
                if (
                    type(seq) is not int
                    or seq != len(columns)
                    or type(cid) is not int
                    or cid < 0
                    or not isinstance(column, str)
                    or not isinstance(collation, str)
                    or type(descending) is not int
                    or descending not in (0, 1)
                    or type(key) is not int
                    or key not in (0, 1)
                ):
                    raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
                columns.append((seq, cid, column, descending, collation, key))
            if not any(column[5] for column in columns):
                raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
            indexes.append((table, unique, origin, partial, tuple(columns)))
    return tuple(sorted(indexes))


@cache
def _expected_schema() -> _SchemaCatalog:
    """Cache SQLite's exact stored representation of only our trusted schema."""
    with closing(sqlite3.connect(":memory:")) as reference:
        reference.executescript(_SCHEMA)
        objects = tuple(
            (row[0], row[1], row[2], row[3])
            for row in reference.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_schema "
                "WHERE type IN ('table', 'trigger') ORDER BY type, name"
            )
        )
        tables = tuple(row[1] for row in objects if row[0] == "table")
        return _SchemaCatalog(objects, _unique_indexes(reference, tables))


def _validate_existing_schema(
    connection: sqlite3.Connection, *, allow_empty: bool = False
) -> None:
    """Validate tables, triggers and conflict identities without repairing anything.

    ASCII case-insensitive discovery catches identifier collisions, while exact
    row/definition comparison deliberately rejects differently authored schemas.
    Keep every matching row: tables and triggers can occupy the same name in
    different namespaces. Unknown triggers on governed tables also fail closed.
    """
    expected = _expected_schema()
    names = tuple(row[1] for row in expected.objects)
    tables = tuple(row[1] for row in expected.objects if row[0] == "table")
    name_parameters = ", ".join("?" for _ in names)
    table_parameters = ", ".join("?" for _ in tables)
    try:
        objects = tuple(
            (row[0], row[1], row[2], row[3])
            for row in connection.execute(
                f"SELECT type, name, tbl_name, sql FROM sqlite_schema "
                f"WHERE name COLLATE NOCASE IN ({name_parameters}) "
                f"OR (type = 'trigger' AND tbl_name COLLATE NOCASE "
                f"IN ({table_parameters})) ORDER BY type, name",
                names + tables,
            )
        )
        if allow_empty and not objects:
            return
        if objects != expected.objects:
            raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
        if _unique_indexes(connection, tables) != expected.unique_indexes:
            raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE)
    except sqlite3.DatabaseError as error:
        raise RuntimeError(_INCOMPATIBLE_SCHEMA_MESSAGE) from error


_STORED_TIMESTAMP = re.compile(
    rb"[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    rb"\.[0-9]{6}(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


def _read_timestamp(value: object, storage_class: str, field_name: str) -> datetime:
    """Validate SQLite TEXT bytes before Python's broader ISO parser sees them.

    The query preserves the original storage class and fetches bytes to avoid
    SQLite's automatic UTF-8 decoding errors exposing malformed stored contents.
    RunProvenance still owns UTC representability, canonicalization and ordering.
    """
    message = f"stored {field_name} is invalid"
    if (
        storage_class != "text"
        or not isinstance(value, bytes)
        or _STORED_TIMESTAMP.fullmatch(value) is None
    ):
        raise ValueError(message)
    try:
        return datetime.fromisoformat(value.decode("ascii"))
    except ValueError:
        # Includes Gregorian calendar validation; never echo the stored value.
        raise ValueError(message) from None


def _options_json(configuration: RunConfiguration) -> str:
    return json.dumps(
        dict(sorted(configuration.options)),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _read_flag(value: object, storage_class: str, field_name: str) -> bool:
    """Accept only the canonical stored SQLite representation, before coercion."""
    allowed = (1,) if field_name == "synthetic_context" else (0, 1)
    if storage_class != "integer" or type(value) is not int or value not in allowed:
        raise ValueError(f"stored {field_name} is invalid")
    return bool(value)


def _read_permission(
    run: sqlite3.Row, conditions: list[sqlite3.Row]
) -> PermissionProvenance | None:
    """Represent every permission field and condition, or reject the record."""
    metadata = (run["policy_id"], run["policy_version"], run["policy_schema_version"])
    if run["permission_state"] is None:
        if any(value is not None for value in metadata) or conditions:
            raise ValueError("stored permission provenance is inconsistent")
        return None
    try:
        return PermissionProvenance(
            policy_id=run["policy_id"],
            policy_version=run["policy_version"],
            policy_schema_version=run["policy_schema_version"],
            state=PermissionState(run["permission_state"]),
            unresolved_condition_ids=tuple(row["condition_id"] for row in conditions),
        )
    except (TypeError, ValueError):
        raise ValueError("stored permission provenance is inconsistent") from None


def _read_options(payload: object, storage_class: str) -> tuple[tuple[str, str], ...]:
    if storage_class != "text" or not isinstance(payload, str):
        raise ValueError("stored configuration options are invalid")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        values: dict[str, object] = {}
        for name, value in pairs:
            if name in values:
                raise ValueError("stored configuration options are invalid")
            values[name] = value
        return values

    decoded: object = json.loads(payload, object_pairs_hook=unique_object)
    if not isinstance(decoded, dict) or any(
        not isinstance(name, str) or not isinstance(value, str)
        for name, value in decoded.items()
    ):
        raise ValueError("stored configuration options are invalid")
    values = cast(dict[str, str], decoded)
    return tuple(sorted(values.items()))


class SQLiteProvenanceStore:
    """Persist each application-authored run once using relational constraints."""

    def __init__(self, database_path: str | Path) -> None:
        if not isinstance(database_path, (str, Path)):
            raise TypeError("database_path must be a string or Path")
        self._lock = RLock()
        self._connection = sqlite3.connect(str(database_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        try:
            with self._lock:
                self._connection.execute("PRAGMA foreign_keys = ON")
                self._connection.execute("PRAGMA recursive_triggers = ON")
                _validate_existing_schema(self._connection, allow_empty=True)
                self._connection.executescript(_SCHEMA)
                _validate_existing_schema(self._connection)
        except Exception:
            self._connection.close()
            raise

    def close(self) -> None:
        """Close the local database connection."""
        with self._lock:
            self._connection.close()

    def append(self, provenance: RunProvenance) -> None:
        """Atomically append a terminal run; duplicate IDs fail, never update."""
        if not isinstance(provenance, RunProvenance):
            raise TypeError("provenance must be RunProvenance")
        permission = provenance.permission
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO runs (
                    run_id, started_at, completed_at, status, stop_reason,
                    failure_stage, synthetic_context, user_id, role_id,
                    client_id, matter_id, workflow_id, policy_id,
                    policy_version, policy_schema_version, permission_state,
                    configuration_hash, retrieval_called, model_called,
                    is_finalized
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provenance.run_id.value,
                    provenance.started_at.isoformat(timespec="microseconds"),
                    provenance.completed_at.isoformat(timespec="microseconds"),
                    provenance.status.value,
                    None
                    if provenance.stop_reason is None
                    else provenance.stop_reason.value,
                    None
                    if provenance.failure_stage is None
                    else provenance.failure_stage.value,
                    int(provenance.context.synthetic),
                    provenance.context.user_id,
                    provenance.context.role_id,
                    provenance.context.client_id,
                    provenance.context.matter_id,
                    provenance.context.workflow_id,
                    None if permission is None else permission.policy_id,
                    None if permission is None else permission.policy_version,
                    None if permission is None else permission.policy_schema_version,
                    None if permission is None else permission.state.value,
                    provenance.configuration_hash,
                    int(provenance.retrieval_called),
                    int(provenance.model_called),
                    0,
                ),
            )
            configuration = provenance.configuration
            self._connection.execute(
                """
                INSERT INTO run_configurations (
                    run_id, configuration_id, configuration_version,
                    provider_id, provider_version, model_id, model_version,
                    model_content_hash,
                    retrieval_provider_id,
                    retrieval_provider_version, retrieval_limit, options_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provenance.run_id.value,
                    configuration.configuration_id,
                    configuration.configuration_version,
                    configuration.provider_id,
                    configuration.provider_version,
                    configuration.model_id,
                    configuration.model_version,
                    configuration.model_content_hash,
                    configuration.retrieval_provider_id,
                    configuration.retrieval_provider_version,
                    configuration.retrieval_limit,
                    _options_json(configuration),
                ),
            )
            if permission is not None:
                self._connection.executemany(
                    """
                    INSERT INTO run_permission_conditions (run_id, condition_id)
                    VALUES (?, ?)
                    """,
                    [
                        (provenance.run_id.value, condition_id)
                        for condition_id in permission.unresolved_condition_ids
                    ],
                )
            for source in provenance.sources:
                self._connection.execute(
                    """
                    INSERT INTO run_sources (run_id, source_id, source_version)
                    VALUES (?, ?, ?)
                    """,
                    (
                        provenance.run_id.value,
                        source.source_id,
                        source.source_version,
                    ),
                )
                self._connection.executemany(
                    """
                    INSERT INTO run_chunks (
                        run_id, source_id, chunk_id, ordinal, retrieval_position
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            provenance.run_id.value,
                            source.source_id,
                            chunk.chunk_id,
                            chunk.ordinal,
                            chunk.retrieval_position,
                        )
                        for chunk in source.chunks
                    ],
                )
            if provenance.model_called:
                self._connection.execute(
                    """
                    INSERT INTO model_executions (
                        run_id, provider_id, provider_version, model_id, model_version,
                        model_content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        provenance.run_id.value,
                        configuration.provider_id,
                        configuration.provider_version,
                        configuration.model_id,
                        configuration.model_version,
                        configuration.model_content_hash,
                    ),
                )
            finalized = self._connection.execute(
                """
                UPDATE runs SET is_finalized = 1
                WHERE run_id = ? AND is_finalized = 0
                """,
                (provenance.run_id.value,),
            )
            if finalized.rowcount != 1:
                raise sqlite3.IntegrityError("run finalization failed")

    def get(self, run_id: RunId) -> RunProvenance | None:
        """Reconstruct one metadata-only run record."""
        if not isinstance(run_id, RunId):
            raise TypeError("run_id must be a RunId")
        with self._lock:
            run = self._connection.execute(
                """
                SELECT CAST(started_at AS BLOB) AS started_at,
                       typeof(started_at) AS started_at_type,
                       CAST(completed_at AS BLOB) AS completed_at,
                       typeof(completed_at) AS completed_at_type,
                       status, stop_reason, failure_stage, synthetic_context,
                       user_id, role_id, client_id, matter_id, workflow_id,
                       policy_id, policy_version, policy_schema_version,
                       permission_state, configuration_hash, retrieval_called,
                       model_called,
                       typeof(synthetic_context) AS synthetic_context_type,
                       typeof(retrieval_called) AS retrieval_called_type,
                       typeof(model_called) AS model_called_type
                FROM runs WHERE run_id = ? AND is_finalized = 1
                """,
                (run_id.value,),
            ).fetchone()
            if run is None:
                return None
            synthetic = _read_flag(
                run["synthetic_context"],
                run["synthetic_context_type"],
                "synthetic_context",
            )
            retrieval_called = _read_flag(
                run["retrieval_called"],
                run["retrieval_called_type"],
                "retrieval_called",
            )
            model_called = _read_flag(
                run["model_called"], run["model_called_type"], "model_called"
            )
            configuration_row = self._connection.execute(
                "SELECT *, typeof(options_json) AS options_json_type "
                "FROM run_configurations WHERE run_id = ?",
                (run_id.value,),
            ).fetchone()
            if configuration_row is None:
                raise ValueError("stored run is missing configuration provenance")
            condition_rows = self._connection.execute(
                """
                SELECT condition_id FROM run_permission_conditions
                WHERE run_id = ? ORDER BY condition_id
                """,
                (run_id.value,),
            ).fetchall()
            source_rows = self._connection.execute(
                """
                SELECT source_id, source_version FROM run_sources WHERE run_id = ?
                """,
                (run_id.value,),
            ).fetchall()
            chunk_rows = self._connection.execute(
                """
                SELECT source_id, chunk_id, ordinal, retrieval_position
                FROM run_chunks WHERE run_id = ? ORDER BY retrieval_position
                """,
                (run_id.value,),
            ).fetchall()
            model_execution = self._connection.execute(
                "SELECT * FROM model_executions WHERE run_id = ?",
                (run_id.value,),
            ).fetchone()
            chunks_by_source: dict[str, list[ChunkProvenance]] = {
                source["source_id"]: [] for source in source_rows
            }
            for chunk in chunk_rows:
                if chunk["source_id"] not in chunks_by_source:
                    raise ValueError(
                        "stored source/chunk associations are inconsistent"
                    )
                chunks_by_source[chunk["source_id"]].append(
                    ChunkProvenance(
                        chunk_id=chunk["chunk_id"],
                        ordinal=chunk["ordinal"],
                        retrieval_position=chunk["retrieval_position"],
                    )
                )
            if any(not chunks for chunks in chunks_by_source.values()):
                raise ValueError("stored source/chunk associations are inconsistent")
            sources = tuple(
                SourceProvenance(
                    source_id=source["source_id"],
                    source_version=source["source_version"],
                    chunks=tuple(chunks_by_source[source["source_id"]]),
                )
                for source in sorted(
                    source_rows,
                    key=lambda row: (
                        chunks_by_source[row["source_id"]][0].retrieval_position
                    ),
                )
            )

        configuration = RunConfiguration(
            configuration_id=configuration_row["configuration_id"],
            configuration_version=configuration_row["configuration_version"],
            provider_id=configuration_row["provider_id"],
            provider_version=configuration_row["provider_version"],
            model_id=configuration_row["model_id"],
            model_version=configuration_row["model_version"],
            model_content_hash=configuration_row["model_content_hash"],
            retrieval_provider_id=configuration_row["retrieval_provider_id"],
            retrieval_provider_version=(
                configuration_row["retrieval_provider_version"]
            ),
            retrieval_limit=configuration_row["retrieval_limit"],
            options=_read_options(
                configuration_row["options_json"],
                configuration_row["options_json_type"],
            ),
        )
        if model_called != (model_execution is not None):
            raise ValueError("stored model execution provenance is inconsistent")
        if model_execution is not None and (
            model_execution["provider_id"],
            model_execution["provider_version"],
            model_execution["model_id"],
            model_execution["model_version"],
            model_execution["model_content_hash"],
        ) != (
            configuration.provider_id,
            configuration.provider_version,
            configuration.model_id,
            configuration.model_version,
            configuration.model_content_hash,
        ):
            raise ValueError("stored model identity does not match run configuration")

        permission = _read_permission(run, condition_rows)
        return RunProvenance(
            run_id=run_id,
            started_at=_read_timestamp(
                run["started_at"], run["started_at_type"], "started_at"
            ),
            completed_at=_read_timestamp(
                run["completed_at"], run["completed_at_type"], "completed_at"
            ),
            status=RunStatus(run["status"]),
            context=ContextProvenance(
                user_id=run["user_id"],
                role_id=run["role_id"],
                client_id=run["client_id"],
                matter_id=run["matter_id"],
                workflow_id=run["workflow_id"],
                synthetic=synthetic,
            ),
            configuration=configuration,
            configuration_hash=run["configuration_hash"],
            permission=permission,
            retrieval_called=retrieval_called,
            model_called=model_called,
            sources=sources,
            stop_reason=(
                None
                if run["stop_reason"] is None
                else PermissionStopReason(run["stop_reason"])
            ),
            failure_stage=(
                None
                if run["failure_stage"] is None
                else FailureStage(run["failure_stage"])
            ),
        )


__all__ = ["SQLiteProvenanceStore"]
