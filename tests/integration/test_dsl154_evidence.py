"""DSL-154 evidence integrity, not new product behavior or release authority."""

from __future__ import annotations

import copy
import importlib.util
import json
import socket
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "dsl154_collector", ROOT / "scripts/collect_dsl154_evidence.py"
)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


@pytest.fixture
def capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(socket, "create_connection", Mock(side_effect=AssertionError))
    result: dict[str, Any] = collector.capture(ROOT, tmp_path / "capture.sqlite3")
    result["identity"] = {
        "product_candidate_sha": collector.CANDIDATE,
        "evidence_tooling_head_sha": "synthetic-tooling-head",
    }
    return result


def test_scenarios_and_metadata(capture: dict[str, Any]) -> None:
    assert capture["passed"] and len(capture["checks"]) == 14
    assert len(capture["executions"]) == 12
    records = {r["execution_label"]: r for r in capture["executions"]}
    for choice, state in (
        ("missing-workflow", "UNKNOWN"),
        ("conditional-role", "CONDITIONAL"),
    ):
        run = records[choice]
        assert run["permission"]["state"] == state
        assert run["observed"]["retrieval_called"] is False
        assert run["observed"]["model_called"] is False
        assert run["output_sha256"] is None
    assert records["conditional-role"]["permission"]["unresolved_condition_ids"]
    for decision in ("approve", "reject", "request_revision"):
        review = records["synthetic-" + decision]["final_review"]
        assert review["state"] == decision.upper()
        assert review["synthetic_demo_decision"]["classification"] == (
            "AUTOMATED_SYNTHETIC_DEMO_DECISION"
        )
    assert all(g["status"] == "PENDING" for g in capture["human_gates"].values())
    history = next(c for c in capture["checks"] if c["scenario_id"] == "history-reopen")
    assert history["passed"]
    assert [o["phase"] for o in history["observations"]] == ["baseline", "final"]
    for observation, count in zip(history["observations"], (10, 12), strict=True):
        assert observation["before"] == observation["after"]
        assert len(observation["run_ids"]) == count
        assert not any(observation["guarded_execution_call_counts"].values())


def test_content_not_exported(capture: dict[str, Any]) -> None:
    serialized = collector.canonical(capture)
    assert collector.canonical(json.loads(serialized)) == serialized

    def string_values(value: Any) -> list[str]:
        if isinstance(value, dict):
            return [s for v in value.values() for s in string_values(v)]
        if isinstance(value, list):
            return [s for v in value for s in string_values(v)]
        return [value] if isinstance(value, str) else []

    values = string_values(capture)
    for task in collector.helpers.load_task_pack(ROOT).tasks:
        assert task.task_text not in serialized
        assert task.query not in values
    for p in (ROOT / "src/privilab/adapters/models/resources/governed_fixtures").glob(
        "*.json"
    ):
        value = json.loads(p.read_text())
        if "answer_text" in value:
            assert value["answer_text"] not in serialized
    assert '"answer_text"' not in serialized
    assert '"task_text"' not in serialized
    assert (
        "Synthetic notice text for fixture and provenance validation only."
        not in serialized
    )


def test_three_independent_captures(capture: dict[str, Any], tmp_path: Path) -> None:
    captures = [capture]
    for n in range(2):
        new = collector.capture(ROOT, tmp_path / f"repeat-{n}.sqlite3")
        new["identity"] = capture["identity"]
        captures.append(new)
    result = collector.compare_captures(captures)
    assert result["passed"] and result["distinct_run_ids"] == 36
    captures[1]["executions"][0]["output_sha256"] = "different"
    assert not collector.compare_captures(captures)["passed"]


def test_reused_runs_are_not_independent(capture: dict[str, Any]) -> None:
    assert not collector.compare_captures([capture, capture, capture])["passed"]


@pytest.mark.parametrize(
    "change",
    [
        "src/privilab/main.py",
        "uv.lock",
        "scripts/collect_gate5_evidence.py",
        "docs/product/evidence/gate5/manifest.json",
    ],
)
def test_candidate_or_history_drift_refused(
    change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_git(root: Path, *args: str) -> str:
        if args[0] == "status":
            return ""
        if args[0] == "merge-base":
            return str(collector.CANDIDATE)
        return change

    monkeypatch.setattr(collector, "git", fake_git)
    with pytest.raises(
        ValueError, match="HISTORICAL_EVIDENCE_CHANGED|CANDIDATE_RESET_REQUIRED"
    ):
        collector.execution_identity(ROOT)


def test_dirty_checkout_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collector, "git", lambda *a: " M PLANS.md")
    with pytest.raises(ValueError, match="TOOLING_CHECKOUT_NOT_CLEAN"):
        collector.execution_identity(ROOT)


@pytest.mark.parametrize("kind", ["outside", "database", "output", "same", "symlink"])
def test_destinations_preserve_existing(tmp_path: Path, kind: str) -> None:
    base = tmp_path / ".local/dsl154"
    base.mkdir(parents=True)
    database, output = base / "capture.sqlite3", base / "capture.json"
    preserved = None
    if kind == "outside":
        output = tmp_path / "outside.json"
    elif kind in {"database", "output"}:
        preserved = database if kind == "database" else output
        preserved.write_text("prior evidence")
    elif kind == "same":
        output = database
    else:
        (base / "alias").symlink_to(base, target_is_directory=True)
        output = base / "alias/capture.json"
    with pytest.raises(ValueError):
        collector.validate_paths(tmp_path, database, output)
    if preserved:
        assert preserved.read_text() == "prior evidence"


def test_partial_failure_keeps_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = collector.helpers.execute
    calls = 0

    def failing(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("PRIVATE SENTINEL")
        return original(*args, **kwargs)

    monkeypatch.setattr(collector.helpers, "execute", failing)
    result = collector.capture(ROOT, tmp_path / "failed.sqlite3")
    assert not result["passed"] and result["failure_code"] == "CAPTURE_INCOMPLETE"
    assert len(result["executions"]) == 1
    assert "PRIVATE SENTINEL" not in collector.canonical(result)


def test_observations_do_not_copy_expected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = collector.helpers.observed

    def wrong(view: Any) -> dict[str, Any]:
        result: dict[str, Any] = original(view)
        result["model_called"] = not result["model_called"]
        return result

    monkeypatch.setattr(collector.helpers, "observed", wrong)
    result = collector.capture(ROOT, tmp_path / "wrong.sqlite3")
    assert not result["passed"]
    assert all(
        not c["passed"]
        for c in result["checks"]
        if c["scenario_id"].startswith("trade-regulatory.")
    )


def test_replay_attempt_is_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = collector.helpers.page

    def replay(*args: Any, **kwargs: Any) -> Any:
        if args[1].startswith("/runs") and len(args) == 2:
            try:
                collector.helpers.RunService.run(None)
            except (RuntimeError, TypeError):
                pass
        return original(*args, **kwargs)

    monkeypatch.setattr(collector.helpers, "page", replay)
    result = collector.capture(ROOT, tmp_path / "replay.sqlite3")
    assert not result["passed"]
    history = next(c for c in result["checks"] if c["scenario_id"] == "history-reopen")
    assert all(
        o["guarded_execution_call_counts"]["run"] > 0 for o in history["observations"]
    )


def test_failed_or_different_identity_not_repeatable(capture: dict[str, Any]) -> None:
    changed = copy.deepcopy(capture)
    changed["identity"]["evidence_tooling_head_sha"] = "different-head"
    assert not collector.compare_captures([capture, changed, capture])[
        "same_execution_identity"
    ]
    changed["passed"] = False
    assert not collector.compare_captures([capture, changed, capture])[
        "all_captures_passed"
    ]


@pytest.mark.parametrize(
    ("baseline_fails", "final_fails"),
    [(False, False), (False, True), (True, False), (True, True)],
    ids=["pass-pass", "pass-fail", "fail-pass", "fail-fail"],
)
def test_history_observation_failures_are_not_masked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    baseline_fails: bool,
    final_fails: bool,
) -> None:
    original_reopen = collector.helpers.reopen_evidence
    original_page = collector.helpers.page
    observations: list[dict[str, Any]] = []
    failures = (baseline_fails, final_fails)

    def reopen(*args: Any, **kwargs: Any) -> Any:
        fail = failures[len(observations)]
        injected = False

        def page(*args: Any, **kwargs: Any) -> Any:
            nonlocal injected
            if fail and not injected:
                injected = True
                with pytest.raises(RuntimeError, match="REPLAY_FORBIDDEN"):
                    collector.helpers.RunService.run(None)
            return original_page(*args, **kwargs)

        with patch.object(collector.helpers, "page", page):
            observed = original_reopen(*args, **kwargs)
        observations.append(copy.deepcopy(observed))
        return observed

    monkeypatch.setattr(collector.helpers, "reopen_evidence", reopen)
    result = collector.capture(ROOT, tmp_path / "history-truth-table.sqlite3")
    assert len(observations) == 2
    assert [o["passed"] for o in observations] == [
        not baseline_fails,
        not final_fails,
    ]
    # The independent review's FAIL/PASS reproduction fails here on prior H.
    assert result["passed"] is (not any(failures))
    history = next(c for c in result["checks"] if c["scenario_id"] == "history-reopen")
    assert history["passed"] is (not any(failures))
    assert [o["phase"] for o in history["observations"]] == ["baseline", "final"]
    for retained, observed, failed in zip(
        history["observations"], observations, failures, strict=True
    ):
        assert retained["guarded_execution_call_counts"]["run"] == int(failed)
        for key, value in observed.items():
            assert retained[key] == value
    if any(failures):
        assert not collector.compare_captures([result])["all_captures_passed"]


@pytest.mark.parametrize("kind", ["missing", "duplicate"])
def test_required_history_observation_cardinality(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    original = collector.helpers.capture

    def changed(root: Path, database: Path) -> Any:
        if kind == "missing":
            with patch.object(
                collector.helpers,
                "reopen_evidence",
                return_value={"scenario_id": "history-reopen", "passed": False},
            ):
                return original(root, database)
        result = original(root, database)
        prior = next(
            c for c in result["scenarios"] if c["scenario_id"] == "history-reopen"
        )
        collector.helpers.reopen_evidence(
            collector.Settings(preview_database=database), prior["run_ids"]
        )
        return result

    monkeypatch.setattr(collector.helpers, "capture", changed)
    result = collector.capture(ROOT, tmp_path / "cardinality.sqlite3")
    history = next(c for c in result["checks"] if c["scenario_id"] == "history-reopen")
    assert not result["passed"] and not history["passed"]
    assert [o["phase"] for o in history["observations"]] == (
        ["final"] if kind == "missing" else ["baseline", "baseline", "final"]
    )
    assert all(o["passed"] for o in history["observations"])


@pytest.mark.parametrize("attempt", [0, 1], ids=["baseline", "final"])
@pytest.mark.parametrize(
    "missing",
    [
        "run_ids",
        "before",
        "after",
        "persistence_unchanged",
        "guarded_execution_call_counts",
        "http_statuses",
        "draft_and_citation_work_area_absent",
        "passed",
    ],
)
def test_incomplete_history_observation_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attempt: int, missing: str
) -> None:
    original = collector.helpers.reopen_evidence
    calls = 0

    def incomplete(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        observed = original(*args, **kwargs)
        if calls == attempt:
            del observed[missing]
            observed["answer_text"] = "PRIVATE HISTORY SENTINEL"
        calls += 1
        return observed

    monkeypatch.setattr(collector.helpers, "reopen_evidence", incomplete)
    result = collector.capture(ROOT, tmp_path / "incomplete.sqlite3")
    history = next(c for c in result["checks"] if c["scenario_id"] == "history-reopen")
    assert not result["passed"] and not history["passed"]
    # Missing passed makes the unchanged historical helper itself raise;
    # its observed metadata must already have been retained by our observer.
    assert len(history["observations"]) == (
        1 if missing == "passed" and attempt == 0 else 2
    )
    assert "PRIVATE HISTORY SENTINEL" not in collector.canonical(result)
    assert not collector.history_observation_passed(history["observations"][attempt])


@pytest.mark.parametrize("attempt", [0, 1], ids=["baseline", "final"])
def test_interrupted_history_attempt_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attempt: int
) -> None:
    original = collector.helpers.reopen_evidence
    calls = 0

    def interrupted(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        current = calls
        calls += 1
        if current == attempt:
            raise RuntimeError("PRIVATE HISTORY EXCEPTION")
        return original(*args, **kwargs)

    monkeypatch.setattr(collector.helpers, "reopen_evidence", interrupted)
    result = collector.capture(ROOT, tmp_path / "interrupted.sqlite3")
    history = next(c for c in result["checks"] if c["scenario_id"] == "history-reopen")
    assert not result["passed"] and not history["passed"]
    assert result["failure_code"] == "CAPTURE_INCOMPLETE"
    assert len(history["observations"]) == attempt + 1
    assert history["observations"][attempt]["completed"] is False
    assert history["observations"][attempt]["passed"] is False
    assert history["observations"][attempt]["attempted_run_ids"]
    if attempt:
        assert collector.history_observation_passed(history["observations"][0])
    assert "PRIVATE HISTORY EXCEPTION" not in collector.canonical(result)


def test_history_survives_later_baseline_composition_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = collector.helpers.capture

    def interrupted(*args: Any, **kwargs: Any) -> Any:
        original(*args, **kwargs)
        raise RuntimeError("PRIVATE COMPOSITION EXCEPTION")

    monkeypatch.setattr(collector.helpers, "capture", interrupted)
    result = collector.capture(ROOT, tmp_path / "composition.sqlite3")
    history = next(c for c in result["checks"] if c["scenario_id"] == "history-reopen")
    assert not result["passed"] and not history["passed"]
    assert len(history["observations"]) == 1
    assert collector.history_observation_passed(history["observations"][0])
    assert result["failure_code"] == "CAPTURE_INCOMPLETE"
    assert "PRIVATE COMPOSITION EXCEPTION" not in collector.canonical(result)
