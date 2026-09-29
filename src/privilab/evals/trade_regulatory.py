"""Explicit local fixture composition and golden evidence for DSL-117.

No artifact discovery or reads occur during import. This composes existing controls;
it supplies no new evaluator, permission engine, provider, or persistence contract.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path
from typing import Any

from privilab.adapters.retrieval import SQLiteFtsRetrievalProvider
from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.application import RunService, parse_permission_policy
from privilab.application.permissions import PermissionPolicy
from privilab.application.run_review import RunReviewService, RunReviewView
from privilab.application.trade_regulatory_tasks import (
    VERSION,
    DomainTask,
    load_task_pack,
    source_document,
)
from privilab.domain import (
    ChunkId,
    RetrievalChunk,
    RetrievalSource,
    SourceEntitlement,
    SourceId,
)


def task_policy() -> PermissionPolicy:
    """Fixed engineering fixture policy, independent of task/source assertions."""
    return parse_permission_policy(
        {
            "schema_version": 1,
            "policy_id": "policy.trade-regulatory-fixture.001",
            "policy_version": VERSION,
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
                    "rule_id": name,
                    "effect": effect,
                    "condition_ids": [],
                    "match": {
                        "user_id": "synthetic-user-001",
                        "role_id": role,
                        "client_id": "synthetic-client-001",
                        "matter_id": "synthetic-matter-001",
                        "workflow_id": "synthetic-workflow-001",
                    },
                }
                for name, role, effect in (
                    ("researcher", "synthetic-researcher", "ALLOW"),
                    ("blocked", "synthetic-blocked", "BLOCK"),
                )
            ],
        }
    )


@contextmanager
def open_task_run(
    repository_root: Path,
    task_id: str,
    *,
    task_version: str = VERSION,
    database_path: str | Path = ":memory:",
) -> Iterator[tuple[DomainTask, RunService, SQLiteProvenanceStore]]:
    """Explicitly load one registered task and compose the existing governed chain."""
    task = load_task_pack(repository_root).select(task_id, task_version)
    if str(database_path) != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        retrieval = stack.enter_context(closing(SQLiteFtsRetrievalProvider(":memory:")))
        store = stack.enter_context(closing(SQLiteProvenanceStore(database_path)))
        for ref in task.sources:
            document = source_document(repository_root, ref)
            source_id = SourceId(ref.source_id)
            workflow = "synthetic-workflow-001"
            if (
                task.scenario_class == "MALICIOUS_SOURCE_INJECTION"
                and ref.corpus_id == "corpus.synthetic-trade-notice.001"
            ):
                workflow = "synthetic-other-workflow"
            retrieval.index_source(
                RetrievalSource(
                    source_id=source_id,
                    source_version=ref.source_version,
                    title=document["title"],
                    chunks=(
                        RetrievalChunk(
                            ChunkId(ref.chunk_id), source_id, 0, document["text"]
                        ),
                    ),
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
            policy=task_policy(),
            retrieval_provider=retrieval,
            fixture_id=task.model_fixture_ref[0],
            provenance_store=store,
            configuration_id="trade-regulatory-fixture",
            configuration_version=VERSION,
            retrieval_provider_id="sqlite-fts5",
            retrieval_provider_version="1",
            options=task.configuration_options,
        )
        yield task, service, store


def observed(view: RunReviewView) -> dict[str, Any]:
    """Project actual existing evidence, never derive evaluator or review results."""
    run = view.run
    evaluation = view.evaluation
    return {
        "permission_state": run.permission.state.value if run.permission else None,
        "run_status": run.status.value,
        "retrieval_called": run.retrieval_called,
        "model_called": run.model_called,
        "criteria": {}
        if evaluation is None
        else {c.criterion_id: c.status.value for c in evaluation.criteria},
        "gate": None if evaluation is None else evaluation.gate_status.value,
        "review_state": view.review_state,
        "allowed_decisions": [d.value for d in view.allowed_decisions],
    }


def run_golden(repository_root: Path) -> tuple[tuple[str, bool], ...]:
    pack = load_task_pack(repository_root)
    results: list[tuple[str, bool]] = []
    for case in pack.cases:
        with open_task_run(
            repository_root, case.domain_task_id, task_version=case.domain_task_version
        ) as (task, service, store):
            outcome, view = RunReviewService(store, store).execute(
                service,
                context=task.context,
                task_text=task.task_text,
                query=task.query,
            )
            restored = store.get(outcome.run_id)
            results.append(
                (
                    case.case_id,
                    observed(view) == case.expected.as_dict()
                    and restored == view.run
                    and restored.configuration.options
                    == case.expected_configuration_options
                    and store.get_evaluation(outcome.run_id) == view.evaluation
                    and view.review is None,
                )
            )
    return tuple(results)


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline DSL-117 golden evaluation")
    parser.add_argument("--root", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        results = run_golden(arguments.root)
    except (OSError, TypeError, ValueError) as error:
        raise SystemExit("DSL-117 golden artifact validation failed") from error
    for identity, matched in results:
        print(f"{'PASS' if matched else 'FAIL'}: {identity}")
    if not results or not all(matched for _, matched in results):
        raise SystemExit("DSL-117 golden outcomes did not match")
    print(f"PASS: {len(results)} deterministic offline golden cases matched")


if __name__ == "__main__":
    main()
