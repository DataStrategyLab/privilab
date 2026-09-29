"""Versioned synthetic composition for the persistent local fixture preview."""

import hashlib
import json
from collections.abc import Iterator
from contextlib import ExitStack, closing, contextmanager
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any

from privilab.adapters.retrieval import SQLiteFtsRetrievalProvider
from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.application import RunService, parse_permission_policy
from privilab.domain import (
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

PREVIEW_VERSION = "1.1.0"
TASK_TEXT = "Summarize only the supplied synthetic chunks."
QUERY = "synthetic"

STANDARD_CONTEXT = SyntheticRequestContext(
    user=UserContext(UserIdentity("synthetic-user-001"), Role("synthetic-researcher")),
    client=ClientContext("synthetic-client-001"),
    matter=MatterContext("synthetic-matter-001"),
    workflow=WorkflowContext("synthetic-workflow-001"),
)
CONTEXT_CHOICES = (
    ("standard", "Standard synthetic researcher", STANDARD_CONTEXT),
    (
        "blocked-role",
        "Synthetic researcher with blocked role",
        replace(
            STANDARD_CONTEXT,
            user=UserContext(
                UserIdentity("synthetic-user-001"), Role("synthetic-blocked")
            ),
        ),
    ),
    (
        "missing-workflow",
        "Synthetic researcher with missing workflow",
        replace(STANDARD_CONTEXT, workflow=None),
    ),
    (
        "conditional-role",
        "Synthetic researcher with conditional role",
        replace(
            STANDARD_CONTEXT,
            user=UserContext(
                UserIdentity("synthetic-user-001"), Role("synthetic-conditional")
            ),
        ),
    ),
    ("critical-citation-failure", "Critical citation failure", STANDARD_CONTEXT),
    ("malicious-source", "Malicious retrieved source", STANDARD_CONTEXT),
)


@contextmanager
def open_preview_run(
    database_path: str | Path = ":memory:",
    *,
    context_choice: str = "standard",
    corpus_root: Path | None = None,
) -> Iterator[tuple[RunService, SQLiteProvenanceStore]]:
    """Compose one attempt with transient retrieval and explicitly selected storage."""
    if context_choice not in {key for key, _, _ in CONTEXT_CHOICES}:
        raise ValueError("unknown preview scenario")
    if str(database_path) != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    policy = parse_permission_policy(
        {
            "schema_version": 1,
            "policy_id": "policy.synthetic-preview.001",
            "policy_version": PREVIEW_VERSION,
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
                    "rule_id": rule_id,
                    "effect": effect,
                    "match": {
                        "user_id": "synthetic-user-001",
                        "role_id": role,
                        "client_id": "synthetic-client-001",
                        "matter_id": "synthetic-matter-001",
                        "workflow_id": "synthetic-workflow-001",
                    },
                    "condition_ids": conditions,
                }
                for rule_id, role, effect, conditions in (
                    ("standard", "synthetic-researcher", "ALLOW", []),
                    ("blocked-role", "synthetic-blocked", "BLOCK", []),
                    (
                        "conditional-role",
                        "synthetic-conditional",
                        "ALLOW",
                        ["condition-synthetic-001"],
                    ),
                )
            ],
        }
    )
    with ExitStack() as stack:
        retrieval = stack.enter_context(closing(SQLiteFtsRetrievalProvider(":memory:")))
        store = stack.enter_context(closing(SQLiteProvenanceStore(database_path)))
        for source_value, chunk_value, title, text in (
            (
                "synthetic-source-001",
                "synthetic-chunk-001",
                "Synthetic source 001",
                "First caller-supplied synthetic source chunk.",
            ),
            (
                "synthetic-source-002",
                "synthetic-chunk-002",
                "Synthetic source 002",
                "Second caller-supplied synthetic source chunk.",
            ),
        ):
            source_id = SourceId(source_value)
            retrieval.index_source(
                RetrievalSource(
                    source_id=source_id,
                    source_version=PREVIEW_VERSION,
                    title=title,
                    chunks=(RetrievalChunk(ChunkId(chunk_value), source_id, 0, text),),
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
                )
            )
        if context_choice == "malicious-source":
            if corpus_root is None:
                raise ValueError("canonical corpus root is required")
            for fixture_id, chunk_id, workflow in (
                (
                    "corpus.synthetic-injection.001",
                    "synthetic-injection-chunk-001",
                    "synthetic-workflow-001",
                ),
                (
                    "corpus.synthetic-trade-notice.001",
                    "synthetic-trade-notice-chunk-001",
                    "synthetic-other-workflow",
                ),
            ):
                document_id, version, title, text = _corpus_record(
                    corpus_root, fixture_id
                )
                source_id = SourceId(document_id)
                retrieval.index_source(
                    RetrievalSource(
                        source_id=source_id,
                        source_version=version,
                        title=title,
                        chunks=(RetrievalChunk(ChunkId(chunk_id), source_id, 0, text),),
                        entitlements=(
                            SourceEntitlement(
                                source_id,
                                "synthetic-user-001",
                                "synthetic-researcher",
                                "synthetic-client-001",
                                "synthetic-matter-001",
                                workflow,
                            ),
                        ),
                    )
                )
        service = RunService.from_governed_fixture(
            policy=policy,
            retrieval_provider=retrieval,
            fixture_id=(
                "model-output.synthetic-citation-failure.001"
                if context_choice in {"critical-citation-failure", "malicious-source"}
                else "model-output.synthetic-happy-path.001"
            ),
            provenance_store=store,
            configuration_id="p0-synthetic-preview",
            configuration_version=PREVIEW_VERSION,
            retrieval_provider_id="sqlite-fts5",
            retrieval_provider_version="1",
            retrieval_limit=10,
            options=(("scenario", context_choice),),
        )
        yield service, store


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate corpus field")
        result[key] = value
    return result


def _corpus_record(root: Path, fixture_id: str) -> tuple[str, str, str, str]:
    """Read only the configured canonical corpus; content never supplies entitlement."""
    if not root.is_absolute():
        raise ValueError("corpus root must be absolute")
    root = root.resolve(strict=True)
    manifest_path = (root / "manifest.json").resolve(strict=True)
    manifest_path.relative_to(root)
    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8"), object_pairs_hook=_json_object
    )
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema_version", "records"}
        or manifest["schema_version"] != "1"
    ):
        raise ValueError("invalid corpus manifest")
    records = manifest["records"]
    if not isinstance(records, list) or not records:
        raise ValueError("invalid corpus records")
    seen: set[str] = set()
    selected: dict[str, Any] | None = None
    for record in records:
        if not isinstance(record, dict) or set(record) != {
            "id",
            "version",
            "path",
            "content_hash",
            "synthetic",
            "origin",
            "permitted_use_basis",
            "license_ref",
        }:
            raise ValueError("invalid corpus metadata")
        if any(
            not isinstance(record[key], str)
            or not record[key].strip()
            or record[key] != record[key].strip()
            for key in record
            if key != "synthetic"
        ):
            raise ValueError("invalid corpus identifier")
        if record["id"] in seen:
            raise ValueError("duplicate corpus identity")
        seen.add(record["id"])
        if record["id"] == fixture_id:
            selected = record
    if (
        selected is None
        or selected["synthetic"] is not True
        or selected["license_ref"] != "fixture:synthetic-corpus"
        or selected["version"] != "1.0.0"
    ):
        raise ValueError("unsupported synthetic corpus record")
    relative = PurePosixPath(selected["path"])
    if (
        relative.parts[:2] != ("fixtures", "corpus")
        or ".." in relative.parts
        or "\\" in selected["path"]
    ):
        raise ValueError("invalid corpus path")
    path = root.joinpath(*relative.parts[2:]).resolve(strict=True)
    path.relative_to(root)
    payload = path.read_bytes()
    if selected["content_hash"] != "sha256:" + hashlib.sha256(payload).hexdigest():
        raise ValueError("corpus hash mismatch")
    document = json.loads(payload, object_pairs_hook=_json_object)
    if (
        not isinstance(document, dict)
        or set(document) != {"document_id", "title", "text", "synthetic"}
        or document["synthetic"] is not True
    ):
        raise ValueError("invalid corpus document")
    for key in ("document_id", "title", "text"):
        value = document[key]
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise ValueError("invalid corpus text")
        value.encode("utf-8")
    expected_id = {
        "corpus.synthetic-injection.001": "synthetic-injection-001",
        "corpus.synthetic-trade-notice.001": "synthetic-trade-notice-001",
    }[fixture_id]
    if document["document_id"] != expected_id:
        raise ValueError("corpus document identity mismatch")
    return expected_id, selected["version"], document["title"], document["text"]
