"""Versioned synthetic composition for the current-run-only local preview."""

from collections.abc import Iterator
from contextlib import ExitStack, closing, contextmanager
from dataclasses import replace

from privilab.adapters.retrieval import SQLiteFtsRetrievalProvider
from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.application import ProvenanceStore, RunService, parse_permission_policy
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

PREVIEW_VERSION = "1.0.0"
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
)


@contextmanager
def open_preview_run() -> Iterator[tuple[RunService, ProvenanceStore]]:
    """Compose one isolated attempt; discard both databases after rendering."""
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
        store = stack.enter_context(closing(SQLiteProvenanceStore(":memory:")))
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
        service = RunService.from_governed_fixture(
            policy=policy,
            retrieval_provider=retrieval,
            fixture_id="model-output.synthetic-happy-path.001",
            provenance_store=store,
            configuration_id="p0-synthetic-preview",
            configuration_version=PREVIEW_VERSION,
            retrieval_provider_id="sqlite-fts5",
            retrieval_provider_version="1",
            retrieval_limit=10,
        )
        yield service, store
