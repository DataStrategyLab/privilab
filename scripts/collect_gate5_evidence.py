"""Offline DSL-120 evidence tooling; no product or release authority."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import subprocess
from contextlib import ExitStack, closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from fastapi import FastAPI
from starlette.types import Message, Scope

from privilab.adapters.models import FixtureModelProvider
from privilab.adapters.retrieval import SQLiteFtsRetrievalProvider
from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.application import RunId, RunService, run_review
from privilab.application.run_review import (
    ReviewDecision,
    RunReviewService,
    RunReviewView,
)
from privilab.application.trade_regulatory_tasks import load_task_pack
from privilab.config import Settings
from privilab.evals.trade_regulatory import observed
from privilab.main import create_app

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = "8d4bad1833431452bd6e99d2c238f5aa51cebbf5"
TABLES = (
    "runs",
    "run_configurations",
    "run_permission_conditions",
    "run_sources",
    "run_chunks",
    "model_executions",
    "model_telemetry",
    "run_evaluations",
    "human_reviews",
)
HAPPY = "trade-regulatory.grounded-happy-path"


def canonical(value: object) -> str:
    """Stable bytes for the same evidence; fresh run identities may differ."""
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        + "\n"
    )


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical(value).encode()).hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def execution_identity(root: Path) -> dict[str, Any]:
    """Reject dirty or material changes rather than mislabel a candidate."""
    if git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("TOOLING_CHECKOUT_NOT_CLEAN")
    permitted = {
        "PLANS.md",
        "docs/product/evidence/README.md",
        "scripts/collect_gate5_evidence.py",
        "tests/integration/test_gate5_evidence.py",
    }
    changed = git(root, "diff", "--name-only", CANDIDATE, "HEAD").splitlines()
    if any(
        p not in permitted and not p.startswith("docs/product/evidence/gate5/")
        for p in changed
    ):
        raise ValueError("CANDIDATE_RESET_REQUIRED")
    return {
        "tested_candidate_sha": CANDIDATE,
        "evidence_tooling_head_sha": git(root, "rev-parse", "HEAD"),
        "evidence_commit_sha": None,
        "branch": git(root, "branch", "--show-current"),
        "working_tree_clean": True,
        "product_paths_unchanged": True,
        "collector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def validate_paths(root: Path, database: Path, output: Path) -> tuple[Path, Path]:
    base = root.resolve() / ".local/gate5"
    resolved = (database.resolve(), output.resolve())
    for original, path in zip((database, output), resolved, strict=True):
        if not path.is_relative_to(base) or path == base or original.is_symlink():
            raise ValueError("CAPTURE_PATH_OUTSIDE_IGNORED_ROOT")
        if path.exists():
            raise ValueError("CAPTURE_PATH_ALREADY_EXISTS")
    if (
        resolved[0] == resolved[1]
        or resolved[0].suffix != ".sqlite3"
        or resolved[1].suffix != ".json"
    ):
        raise ValueError("CAPTURE_PATH_INVALID")
    return resolved


async def request(
    app: FastAPI, path: str, form: dict[str, str] | None = None
) -> tuple[int, str]:
    """Exercise native routes without an HTTP client dependency or network."""
    messages: list[Message] = []
    body = b"" if form is None else urlencode(form).encode()

    async def receive() -> Message:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: Message) -> None:
        messages.append(message)

    scope = cast(
        Scope,
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET" if form is None else "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 8000),
        },
    )
    await app(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    html = b"".join(
        m.get("body", b"") for m in messages if m["type"] == "http.response.body"
    )
    return cast(int, start["status"]), html.decode()


def page(
    app: FastAPI, path: str, form: dict[str, str] | None = None
) -> tuple[int, str]:
    return asyncio.run(request(app, path, form))


def snapshot(database: Path) -> dict[str, Any]:
    """Hash every persisted row, including child evidence, using a read-only DB."""
    result: dict[str, Any] = {}
    with closing(
        sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    ) as connection:
        for table in TABLES:
            rows = connection.execute(f'SELECT * FROM "{table}"').fetchall()
            ordered = sorted([list(row) for row in rows], key=canonical)
            result[table] = {"row_count": len(rows), "sha256": digest(ordered)}
    return result


def view_for(database: Path, identity: str) -> RunReviewView:
    with closing(SQLiteProvenanceStore(database)) as store:
        return RunReviewService(store, store).get(RunId(identity))


def projection(view: RunReviewView) -> dict[str, Any]:
    """Explicit metadata allowlist. No answer or task bodies enter this function."""
    run, evaluation, review = view.run, view.evaluation, view.review
    config = run.configuration
    return {
        "run_id": run.run_id.value,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat(),
        "configuration_id": config.configuration_id,
        "configuration_version": config.configuration_version,
        "configuration_hash": run.configuration_hash,
        "configuration_options": dict(config.options),
        "provider_id": config.provider_id,
        "provider_version": config.provider_version,
        "model_id": config.model_id,
        "model_version": config.model_version,
        "model_content_hash": config.model_content_hash,
        "source_ids": [source.source_id for source in run.sources],
        "chunk_ids": [
            chunk.chunk_id for source in run.sources for chunk in source.chunks
        ],
        "observed": observed(view),
        "evaluation": None
        if evaluation is None
        else {
            "evaluated_at": evaluation.evaluated_at.isoformat(),
            "task_id": evaluation.task_id,
            "task_version": evaluation.task_version,
            "rubric_id": evaluation.rubric_id,
            "rubric_version": evaluation.rubric_version,
            "criteria": [
                {
                    "criterion_id": c.criterion_id,
                    "criterion_version": c.criterion_version,
                    "evaluator_kind": c.evaluator_kind.value,
                    "evaluator_version": c.evaluator_version,
                    "criticality": c.criticality.value,
                    "status": c.status.value,
                }
                for c in evaluation.criteria
            ],
        },
        "synthetic_demo_decision": None
        if review is None
        else {
            "classification": "AUTOMATED_SYNTHETIC_DEMO_DECISION",
            "run_id": review.run_id.value,
            "decision": review.decision.value,
            "reviewer_id": review.reviewer_id,
            "reviewed_at": review.reviewed_at.isoformat(),
            "operator_role": "codex-engineering-evidence",
        },
    }


def execute(app: FastAPI, database: Path, task_id: str) -> tuple[dict[str, Any], str]:
    with closing(SQLiteProvenanceStore(database)) as store:
        before = set(store.recent_run_ids())
    status, html = page(app, "/runs", {"context_choice": task_id})
    with closing(SQLiteProvenanceStore(database)) as store:
        added = set(store.recent_run_ids()) - before
    if status != 200 or len(added) != 1:
        raise ValueError("SCENARIO_EXECUTION_INCOMPLETE")
    record = projection(view_for(database, added.pop().value))
    record["http_status"] = status
    return record, html


def reopen_evidence(settings: Settings, identities: list[str]) -> dict[str, Any]:
    before = snapshot(settings.preview_database)
    app = create_app(settings)
    statuses: list[int] = []
    no_bodies = True
    guards: list[Mock] = []
    with ExitStack() as stack:
        for owner, name in (
            (RunService, "run"),
            (FixtureModelProvider, "generate"),
            (SQLiteFtsRetrievalProvider, "retrieve"),
            (run_review, "evaluate"),
        ):
            guard = stack.enter_context(
                patch.object(owner, name, side_effect=RuntimeError("REPLAY_FORBIDDEN"))
            )
            guards.append(guard)
        for path in ["/runs", *("/runs/" + identity for identity in identities)]:
            status, html = page(app, path)
            statuses.append(status)
            no_bodies = (
                no_bodies
                and 'class="answer"' not in html
                and 'id="research-result"' not in html
                and 'id="draft-citations"' not in html
                and 'class="citations"' not in html
            )
    after = snapshot(settings.preview_database)
    calls = [guard.call_count for guard in guards]
    passed = (
        before == after
        and all(status == 200 for status in statuses)
        and no_bodies
        and not any(calls)
    )
    return {
        "scenario_id": "history-reopen",
        "run_ids": identities,
        "before": before,
        "after": after,
        "persistence_unchanged": before == after,
        "guarded_execution_call_counts": dict(
            zip(("run", "model", "retrieval", "evaluation"), calls, strict=True)
        ),
        "http_statuses": statuses,
        "draft_and_citation_work_area_absent": no_bodies,
        "passed": passed,
    }


def capture(root: Path, database: Path) -> dict[str, Any]:
    pack = load_task_pack(root)
    settings = Settings(
        preview_database=database, preview_corpus_root=root / "fixtures/corpus"
    )
    app = create_app(settings)
    scenarios: list[dict[str, Any]] = []
    rerun: dict[str, Any] | None = None
    for case in pack.cases:
        record, html = execute(app, database, case.domain_task_id)
        task = pack.select(case.domain_task_id, case.domain_task_version)
        record.update(
            {
                "scenario_id": case.domain_task_id,
                "scenario_class": task.scenario_class,
                "task_id": case.domain_task_id,
                "task_version": case.domain_task_version,
                "golden_case_id": case.case_id,
                "golden_case_version": case.case_version,
                "expected": case.expected.as_dict(),
                "expected_configuration_options": dict(
                    case.expected_configuration_options
                ),
                "substantive_review": {
                    "status": task.substantive_review.status,
                    "reviewer_id": task.substantive_review.reviewer_id,
                    "reviewed_at": task.substantive_review.reviewed_at,
                },
                "prospect_demo_eligible": task.prospect_demo_eligible,
                "limitation": (
                    "Synthetic fixture control exercise; "
                    "no substantive or release approval."
                ),
            }
        )
        record["passed"] = (
            record["observed"] == record["expected"]
            and record["configuration_options"]
            == record["expected_configuration_options"]
        )
        if task.scenario_class == "INSUFFICIENT_SOURCE":
            bounded = (
                "The supplied source does not establish "
                "a licensing requirement or penalty."
            ) in html
            record["insufficient_source_qualification_present"] = bounded
            record["passed"] = record["passed"] and bounded
        scenarios.append(record)
        if task.scenario_class == "PERMISSION_BLOCK":
            stopped = projection(view_for(database, record["run_id"]))
            rerun, _ = execute(app, database, HAPPY)
            rerun.update(
                {
                    "scenario_id": "safe-independent-rerun",
                    "after_run_id": record["run_id"],
                    "expected": pack.select(HAPPY).expected.as_dict(),
                }
            )
            unchanged = projection(view_for(database, record["run_id"])) == stopped
            rerun["stopped_run_unchanged"] = unchanged
            rerun["passed"] = (
                unchanged
                and rerun["run_id"] != record["run_id"]
                and rerun["observed"] == rerun["expected"]
            )
    for decision in ReviewDecision:
        record, _ = execute(app, database, HAPPY)
        initial = record
        status, _ = page(
            app, "/runs/" + record["run_id"] + "/review", {"decision": decision.value}
        )
        final = projection(view_for(database, record["run_id"]))
        scenarios.append(
            {
                "scenario_id": "synthetic-" + decision.value.lower(),
                "before_decision": initial,
                "after_decision": final,
                "http_status": status,
                "expected_decision": decision.value,
                "passed": status == 303
                and final["observed"]["review_state"] == decision.value
                and final["synthetic_demo_decision"] is not None
                and final["synthetic_demo_decision"]["decision"] == decision.value
                and final["observed"]["allowed_decisions"] == [],
            }
        )
    blocked = next(
        r
        for r in scenarios
        if r["scenario_id"] == "trade-regulatory.critical-eval-failure"
    )
    before = snapshot(database)
    status, _ = page(
        app, "/runs/" + blocked["run_id"] + "/review", {"decision": "APPROVE"}
    )
    after = snapshot(database)
    rejected = projection(view_for(database, blocked["run_id"]))
    scenarios.append(
        {
            "scenario_id": "generated-block-approval-denied",
            "run_id": blocked["run_id"],
            "http_status": status,
            "observed": rejected["observed"],
            "synthetic_demo_decision": rejected["synthetic_demo_decision"],
            "persistence_unchanged": before == after,
            "passed": status == 409
            and before == after
            and rejected["synthetic_demo_decision"] is None
            and "APPROVE" not in rejected["observed"]["allowed_decisions"],
        }
    )
    with closing(SQLiteProvenanceStore(database)) as store:
        identities = sorted(item.value for item in store.recent_run_ids())
    scenarios.append(reopen_evidence(settings, identities))
    if rerun is None:
        raise ValueError("REQUIRED_SCENARIO_MISSING")
    scenarios.append(rerun)
    return {
        "schema_version": "1",
        "package_id": "dsl-120-gate5",
        "package_version": "1.0.0",
        "execution_kind": "OFFLINE_ASGI_REFERENCE_FIXTURE",
        "scenarios": scenarios,
        "passed": len(scenarios) == 12 and all(r["passed"] for r in scenarios),
        "human_gates": {
            "non_author_approval": None,
            "substantive_approval": None,
            "claims_approval": None,
            "andrew_release_decision": None,
        },
    }


def collect(root: Path, database: Path, output: Path) -> bool:
    database, output = validate_paths(root, database, output)
    identity = execution_identity(root)
    for path in (database, output):
        git(root, "check-ignore", str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive reservations protect prior evidence even if a competing capture starts.
    with database.open("xb"):
        pass
    with output.open("x", encoding="utf-8") as target:
        try:
            result = capture(root, database)
        except Exception:
            result = {
                "schema_version": "1",
                "passed": False,
                "failure_code": "CAPTURE_INCOMPLETE",
                "scenarios": [],
            }
        result["identity"] = identity
        result["captured_at"] = datetime.now(UTC).isoformat()
        target.write(canonical(result))
    return bool(result["passed"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        passed = collect(ROOT, args.database, args.output)
    except Exception:
        raise SystemExit(
            "Gate 5 capture refused; check clean candidate and fresh ignored paths."
        ) from None
    if not passed:
        raise SystemExit(
            "Gate 5 capture failed; bounded evidence retained; "
            "previous captures unchanged."
        )
    print("PASS: 12 Gate 5 scenarios; metadata-only capture written.")


if __name__ == "__main__":
    main()
