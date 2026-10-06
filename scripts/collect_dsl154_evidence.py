"""Offline DSL-154 observation tooling; no product or release authority."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from fastapi import FastAPI

from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.application import RunOutcome, RunService
from privilab.application.run_review import RunReviewService, RunReviewView
from privilab.config import Settings
from privilab.main import create_app

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = "f19f5542105661614c225691c3df780264de8262"
PACKAGE = "dsl-154-prospect-demo"
SPEC = importlib.util.spec_from_file_location(
    "dsl154_historical_helpers", ROOT / "scripts/collect_gate5_evidence.py"
)
assert SPEC is not None and SPEC.loader is not None
helpers = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helpers)


def canonical(value: object) -> str:
    return cast(str, helpers.canonical(value))


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical(value).encode()).hexdigest()


def git(root: Path, *args: str) -> str:
    return cast(str, helpers.git(root, *args))


def execution_identity(root: Path) -> dict[str, Any]:
    """A clean, descendant checkout with a narrow evidence-only path allowlist."""
    if git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("TOOLING_CHECKOUT_NOT_CLEAN")
    if git(root, "merge-base", CANDIDATE, "HEAD") != CANDIDATE:
        raise ValueError("CANDIDATE_ANCESTRY_MISMATCH")
    permitted = {
        "PLANS.md",
        "scripts/collect_dsl154_evidence.py",
        "tests/integration/test_dsl154_evidence.py",
    }
    changed = git(root, "diff", "--name-only", CANDIDATE, "HEAD").splitlines()
    if any(p.startswith("docs/product/evidence/gate5/") for p in changed):
        raise ValueError("HISTORICAL_EVIDENCE_CHANGED")
    if any(
        p not in permitted and not p.startswith("docs/product/evidence/dsl154/")
        for p in changed
    ):
        raise ValueError("CANDIDATE_RESET_REQUIRED")
    return {
        "product_candidate_sha": CANDIDATE,
        "evidence_tooling_head_sha": git(root, "rev-parse", "HEAD"),
        "checkout_sha": git(root, "rev-parse", "HEAD"),
        "branch": git(root, "branch", "--show-current") or None,
        "working_tree_clean": True,
        "product_paths_unchanged": True,
        "historical_gate5_unchanged": True,
        "evidence_only_paths": changed,
        "collector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "helper_sha256": hashlib.sha256(
            (root / "scripts/collect_gate5_evidence.py").read_bytes()
        ).hexdigest(),
    }


def validate_paths(root: Path, database: Path, output: Path) -> tuple[Path, Path]:
    base = root.resolve() / ".local/dsl154"
    resolved = (database.resolve(), output.resolve())
    for original, path in zip((database, output), resolved, strict=True):
        if not path.is_relative_to(base) or path == base:
            raise ValueError("CAPTURE_PATH_OUTSIDE_IGNORED_ROOT")
        # Reject even within-root symlink aliases; captures have one local identity.
        if any(p.is_symlink() for p in (original, *original.parents)):
            raise ValueError("CAPTURE_PATH_SYMLINK")
        if path.exists():
            raise ValueError("CAPTURE_PATH_ALREADY_EXISTS")
    if (
        resolved[0] == resolved[1]
        or resolved[0].suffix != ".sqlite3"
        or resolved[1].suffix != ".json"
    ):
        raise ValueError("CAPTURE_PATH_INVALID")
    return resolved


def projection(view: RunReviewView) -> dict[str, Any]:
    record = cast(dict[str, Any], helpers.projection(view))
    run = view.run
    record.update(
        context=asdict(run.context),
        permission=None
        if run.permission is None
        else {
            "policy_id": run.permission.policy_id,
            "policy_version": run.permission.policy_version,
            "policy_schema_version": run.permission.policy_schema_version,
            "state": run.permission.state.value,
            "unresolved_condition_ids": list(run.permission.unresolved_condition_ids),
        },
        retrieval_configuration={
            "provider_id": run.configuration.retrieval_provider_id,
            "provider_version": run.configuration.retrieval_provider_version,
            "limit": run.configuration.retrieval_limit,
        },
        source_metadata=[asdict(source) for source in run.sources],
        failure_stage=run.failure_stage.value if run.failure_stage else None,
        stop_reason=run.stop_reason.value if run.stop_reason else None,
        latency_usage_cost={
            "status": "N/A_FIXTURE_NO_PROVIDER_TELEMETRY",
            "provider_latency_ns": None,
            "usage": None,
            "cost": None,
            "run_elapsed_seconds": (run.completed_at - run.started_at).total_seconds(),
        },
    )
    return record


def permission_check(
    app: FastAPI, database: Path, choice: str, state: str
) -> dict[str, Any]:
    record, _ = helpers.execute(app, database, choice)
    observed = record["observed"]
    expected = {
        "permission_state": state,
        "run_status": "PERMISSION_STOPPED",
        "retrieval_called": False,
        "model_called": False,
        "criteria": {
            "authorized-source": "UNKNOWN",
            "citation-resolution": "UNKNOWN",
            "permission-boundary": "PASS",
            "provenance-completeness": "PASS",
        },
        "gate": "BLOCK",
        "review_state": "NOT REVIEWABLE",
        "allowed_decisions": [],
    }
    return {
        "scenario_id": choice,
        "run_id": record["run_id"],
        "expected": expected,
        "observed": observed,
        "passed": observed == expected,
    }


def compact_check(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep checks and run references; execution metadata has one canonical list."""
    keys = (
        "scenario_id",
        "run_id",
        "run_ids",
        "after_run_id",
        "passed",
        "expected",
        "observed",
        "http_status",
        "persistence_unchanged",
        "stopped_run_unchanged",
        "insufficient_source_qualification_present",
        "before",
        "after",
        "guarded_execution_call_counts",
        "http_statuses",
        "draft_and_citation_work_area_absent",
        "expected_decision",
    )
    result = {key: raw[key] for key in keys if key in raw}
    if "before_decision" in raw:
        result["run_id"] = raw["before_decision"]["run_id"]
        result["observed_decision"] = raw["after_decision"]["synthetic_demo_decision"]
    return result


def history_observation_passed(observation: dict[str, Any]) -> bool:
    """Require complete observed controls, not merely a helper's success flag."""
    identities = observation.get("run_ids")
    before = observation.get("before")
    after = observation.get("after")
    if (
        observation.get("completed") is not True
        or observation.get("passed") is not True
        or observation.get("scenario_id") != "history-reopen"
        or not isinstance(identities, list)
        or not identities
        or not all(isinstance(identity, str) for identity in identities)
        or len(identities) != len(set(identities))
        or identities != observation.get("attempted_run_ids")
        or not isinstance(before, dict)
        or set(before) != set(helpers.TABLES)
        or before != after
    ):
        return False
    for snapshot in before.values():
        if (
            not isinstance(snapshot, dict)
            or type(snapshot.get("row_count")) is not int
            or snapshot["row_count"] < 0
            or not isinstance(snapshot.get("sha256"), str)
            or not snapshot["sha256"].startswith("sha256:")
            or len(snapshot["sha256"]) != 71
        ):
            return False
    return (
        observation.get("persistence_unchanged") is True
        and observation.get("draft_and_citation_work_area_absent") is True
        and observation.get("http_statuses") == [200] * (len(identities) + 1)
        and observation.get("guarded_execution_call_counts")
        == {name: 0 for name in ("run", "model", "retrieval", "evaluation")}
    )


def capture(root: Path, database: Path) -> dict[str, Any]:
    """Observe native routes and outputs without replacing any execution result."""
    executions: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    history: dict[str, Any] = {
        "scenario_id": "history-reopen",
        "observations": observations,
        "passed": False,
    }
    checks: list[dict[str, Any]] = [history]
    result: dict[str, Any] = {
        "schema_version": "1",
        "package_id": PACKAGE,
        "package_version": "1.0.0",
        "execution_kind": "OFFLINE_ASGI_REFERENCE_FIXTURE",
        "executions": executions,
        "checks": checks,
        "passed": False,
        "human_gates": {
            name: {"status": "PENDING", "reviewer": None, "timestamp": None}
            for name in (
                "substantive_review",
                "human_rehearsal",
                "claims_review",
                "backup_acceptance",
                "independent_review",
                "non_author_review",
                "andrew_release_decision",
            )
        },
    }
    original = RunReviewService.execute
    original_reopen = helpers.reopen_evidence

    def observe_reopen(
        settings: Settings, identities: list[str], *, phase: str = "baseline"
    ) -> dict[str, Any]:
        observation: dict[str, Any] = {
            "phase": phase,
            "attempted_run_ids": list(identities),
            "completed": False,
            "passed": False,
        }
        # Attach before calling: completed observations and interrupted attempts
        # survive even when the historical composition or a later step raises.
        observations.append(observation)
        raw = cast(dict[str, Any], original_reopen(settings, identities))
        keys = (
            "scenario_id",
            "run_ids",
            "before",
            "after",
            "persistence_unchanged",
            "guarded_execution_call_counts",
            "http_statuses",
            "draft_and_citation_work_area_absent",
            "passed",
        )
        observation.update(deepcopy({key: raw[key] for key in keys if key in raw}))
        observation["completed"] = True
        return raw

    def observe(
        instance: RunReviewService, service: RunService, **kwargs: Any
    ) -> tuple[RunOutcome, RunReviewView]:
        outcome, view = original(instance, service, **kwargs)
        record = projection(view)
        output = outcome.result
        record["output_sha256"] = (
            None
            if output is None
            else hashlib.sha256(output.to_json().encode()).hexdigest()
        )
        record["citation_references"] = (
            []
            if output is None
            else [asdict(citation) for citation in output.citations]
        )
        record["citation_references_sha256"] = digest(record["citation_references"])
        executions.append(record)
        return outcome, view

    try:
        with patch.object(RunReviewService, "execute", observe):
            # Re-execute the old scenario composition, never its identity/collector.
            # Only actual checks are consumed; historical package metadata is ignored.
            with patch.object(helpers, "reopen_evidence", observe_reopen):
                baseline = helpers.capture(root, database)
            checks.extend(
                compact_check(check)
                for check in baseline["scenarios"]
                if check["scenario_id"] != "history-reopen"
            )
            settings = Settings(
                preview_database=database, preview_corpus_root=root / "fixtures/corpus"
            )
            app = create_app(settings)
            for choice, state in (
                ("missing-workflow", "UNKNOWN"),
                ("conditional-role", "CONDITIONAL"),
            ):
                checks.append(permission_check(app, database, choice, state))
        with closing(SQLiteProvenanceStore(database)) as store:
            identities = sorted(run.value for run in store.recent_run_ids())
        observe_reopen(settings, identities, phase="final")
        history["passed"] = [o["phase"] for o in observations] == [
            "baseline",
            "final",
        ] and all(history_observation_passed(o) for o in observations)
        labels = {c["run_id"]: c["scenario_id"] for c in checks if "run_id" in c}
        # Denied approval is another check on the existing critical-failure run.
        for record in executions:
            run_id = record["run_id"]
            label = labels[run_id]
            if label == "generated-block-approval-denied":
                label = "trade-regulatory.critical-eval-failure"
            record["execution_label"] = label
            final = projection(helpers.view_for(database, run_id))
            record["final_review"] = {
                "state": final["observed"]["review_state"],
                "allowed_decisions": final["observed"]["allowed_decisions"],
                "synthetic_demo_decision": final["synthetic_demo_decision"],
            }
        result["passed"] = (
            len(checks) == 14
            and len(executions) == 12
            and len({r["run_id"] for r in executions}) == 12
            and all(check["passed"] for check in checks)
        )
    except Exception:
        # Completed observations survive, but no raw exception or content is exported.
        result["failure_code"] = "CAPTURE_INCOMPLETE"
    return result


def stable_projection(record: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "execution_label",
        "configuration_hash",
        "configuration_id",
        "configuration_version",
        "configuration_options",
        "provider_id",
        "provider_version",
        "model_id",
        "model_version",
        "model_content_hash",
        "context",
        "permission",
        "retrieval_configuration",
        "source_metadata",
        "observed",
        "output_sha256",
        "citation_references",
        "citation_references_sha256",
        "failure_stage",
        "stop_reason",
    )
    projected = {key: record[key] for key in fields}
    evaluation = record["evaluation"]
    projected["evaluation"] = (
        None
        if evaluation is None
        else {k: v for k, v in evaluation.items() if k != "evaluated_at"}
    )
    final = record["final_review"]
    decision = final["synthetic_demo_decision"]
    projected["final_review"] = {
        "state": final["state"],
        "allowed_decisions": final["allowed_decisions"],
        "decision": None if decision is None else decision["decision"],
        "classification": None if decision is None else decision["classification"],
    }
    return projected


def compare_captures(captures: list[dict[str, Any]]) -> dict[str, Any]:
    """Fixture equivalence excludes only run IDs, times, and measured elapsed time."""
    ids = [r["run_id"] for c in captures for r in c["executions"]]
    projections = [
        sorted(
            (stable_projection(r) for r in c["executions"]),
            key=lambda r: r["execution_label"],
        )
        for c in captures
    ]
    equal = bool(projections) and all(p == projections[0] for p in projections)
    identities = [c.get("identity") for c in captures]
    same_identity = (
        bool(identities)
        and isinstance(identities[0], dict)
        and identities[0].get("product_candidate_sha") == CANDIDATE
        and bool(identities[0].get("evidence_tooling_head_sha"))
        and all(i == identities[0] for i in identities)
    )
    return {
        "classification": "DETERMINISTIC_FIXTURE_REPEATABILITY",
        "captures": len(captures),
        "executions": len(ids),
        "distinct_run_ids": len(set(ids)),
        "all_captures_passed": all(c["passed"] for c in captures),
        "same_execution_identity": same_identity,
        "material_projections_equal": equal,
        "stable_projection_sha256": [digest(p) for p in projections],
        "passed": len(captures) >= 3
        and len(ids) == len(set(ids))
        and all(c["passed"] for c in captures)
        and equal
        and same_identity,
        "limitation": "Fixed fixture consistency is not live-model stability.",
    }


def collect(root: Path, database: Path, output: Path) -> bool:
    database, output = validate_paths(root, database, output)
    identity = execution_identity(root)
    for path in (database, output):
        git(root, "check-ignore", str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
    with database.open("xb"):
        pass
    with output.open("x", encoding="utf-8") as target:
        result = capture(root, database)
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
            "DSL-154 capture refused; check identity and fresh paths."
        ) from None
    if not passed:
        raise SystemExit("DSL-154 capture failed; bounded observations preserved.")
    print("PASS: 14 DSL-154 checks; 12 executions; metadata-only capture.")


if __name__ == "__main__":
    main()
