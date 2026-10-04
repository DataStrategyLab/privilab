"""Evidence tooling regressions; no new product/evaluator authority."""

from __future__ import annotations

import importlib.util
import json
import socket
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.application import RunId
from privilab.application.run_review import ReviewDecision, RunReviewService
from privilab.config import Settings

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "gate5_collector", ROOT / "scripts/collect_gate5_evidence.py"
)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


@pytest.fixture
def captured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict[str, Any]]:
    monkeypatch.setattr(
        socket,
        "create_connection",
        Mock(side_effect=AssertionError("network forbidden")),
    )
    database = tmp_path / "capture.sqlite3"
    return database, collector.capture(ROOT, database)


def test_complete_capture_and_synthetic_review_identity(
    captured: tuple[Path, dict[str, Any]],
) -> None:
    _, result = captured
    assert result["passed"] and len(result["scenarios"]) == 12
    records = {r["scenario_id"]: r for r in result["scenarios"]}
    stopped = records["trade-regulatory.permission-block"]
    assert stopped["observed"]["retrieval_called"] is False
    assert stopped["observed"]["model_called"] is False
    assert stopped["observed"]["review_state"] == "NOT REVIEWABLE"
    for decision in ReviewDecision:
        record = records["synthetic-" + decision.value.lower()]
        review = record["after_decision"]["synthetic_demo_decision"]
        assert review["classification"] == "AUTOMATED_SYNTHETIC_DEMO_DECISION"
        assert review["reviewer_id"] == "synthetic-local-reviewer"
        assert review["reviewed_at"] and review["decision"] == decision.value
        assert record["before_decision"]["synthetic_demo_decision"] is None
    assert records["generated-block-approval-denied"]["http_status"] == 409
    assert records["history-reopen"]["before"] == records["history-reopen"]["after"]
    assert all(v is None for v in result["human_gates"].values())


def test_canonical_same_evidence_and_fresh_semantics(
    captured: tuple[Path, dict[str, Any]], tmp_path: Path
) -> None:
    _, result = captured
    serialized = collector.canonical(result)
    assert serialized == collector.canonical(json.loads(serialized))
    fresh = collector.capture(ROOT, tmp_path / "fresh.sqlite3")
    original_cases = result["scenarios"][:6]
    fresh_cases = fresh["scenarios"][:6]
    assert [r["observed"] for r in original_cases] == [
        r["observed"] for r in fresh_cases
    ]
    assert {r["run_id"] for r in original_cases}.isdisjoint(
        {r["run_id"] for r in fresh_cases}
    )


def test_no_content_in_export(captured: tuple[Path, dict[str, Any]]) -> None:
    _, result = captured
    text = collector.canonical(result)
    for task in collector.load_task_pack(ROOT).tasks:
        assert task.task_text not in text
        assert json.dumps(task.query) not in text
    fixtures = ROOT / "src/privilab/adapters/models/resources/governed_fixtures"
    for fixture in fixtures.glob("trade_regulatory_*.json"):
        answer = json.loads(fixture.read_text())["answer_text"]
        assert answer not in text
    for forbidden in (
        '"answer_text"',
        '"task_text"',
        '"query"',
        '"snapshot_json"',
        "Synthetic notice text for fixture and provenance validation only.",
    ):
        assert forbidden not in text


def test_reopen_detects_review_write_even_when_html_succeeds(
    captured: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    database, result = captured
    identity = result["scenarios"][0]["run_id"]
    original = collector.page
    changed = False

    def mutating_page(*args: Any, **kwargs: Any) -> Any:
        nonlocal changed
        if not changed:
            store = SQLiteProvenanceStore(database)
            try:
                RunReviewService(store, store).decide(
                    RunId(identity), ReviewDecision.REJECT
                )
            finally:
                store.close()
            changed = True
        return original(*args, **kwargs)

    monkeypatch.setattr(collector, "page", mutating_page)
    evidence = collector.reopen_evidence(
        Settings(preview_database=database), [identity]
    )
    assert evidence["http_statuses"] == [200, 200]
    assert not evidence["persistence_unchanged"] and not evidence["passed"]
    assert evidence["before"]["human_reviews"] != evidence["after"]["human_reviews"]


def test_observation_mismatch_cannot_copy_expected(
    captured: tuple[Path, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = collector.observed

    def wrong(view: Any) -> dict[str, Any]:
        result: dict[str, Any] = original(view)
        result["model_called"] = not result["model_called"]
        return result

    monkeypatch.setattr(collector, "observed", wrong)
    result = collector.capture(ROOT, tmp_path / "mismatch.sqlite3")
    assert result["passed"] is False
    assert all(not r["passed"] for r in result["scenarios"][:6])


@pytest.mark.parametrize(
    "path_kind", ["outside", "existing_db", "existing_output", "same", "symlink"]
)
def test_paths_preserve_prior_evidence(tmp_path: Path, path_kind: str) -> None:
    base = tmp_path / ".local/gate5"
    base.mkdir(parents=True)
    database, output = base / "capture.sqlite3", base / "capture.json"
    sentinel = b"previous evidence must survive"
    preserved: Path | None = None
    if path_kind == "outside":
        output = tmp_path / "outside.json"
    elif path_kind == "existing_db":
        database.write_bytes(sentinel)
        preserved = database
    elif path_kind == "existing_output":
        output.write_bytes(sentinel)
        preserved = output
    elif path_kind == "same":
        output = database
    else:
        outside = tmp_path / "outside"
        outside.mkdir()
        (base / "escape").symlink_to(outside, target_is_directory=True)
        output = base / "escape/capture.json"
    with pytest.raises(ValueError):
        collector.validate_paths(tmp_path, database, output)
    if preserved is not None:
        assert preserved.read_bytes() == sentinel


def test_failure_is_bounded_and_capture_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    base = tmp_path / ".local/gate5"
    database, output = base / "failed.sqlite3", base / "failed.json"
    monkeypatch.setattr(
        collector,
        "execution_identity",
        lambda root: {"tested_candidate_sha": collector.CANDIDATE},
    )
    monkeypatch.setattr(collector, "git", lambda *args: ".local/gate5")
    monkeypatch.setattr(
        collector,
        "capture",
        Mock(side_effect=RuntimeError("PRIVATE SENTINEL prompt/source/answer")),
    )
    assert collector.collect(tmp_path, database, output) is False
    original = output.read_bytes()
    assert b"PRIVATE SENTINEL" not in original
    assert json.loads(original)["failure_code"] == "CAPTURE_INCOMPLETE"
    with pytest.raises(ValueError):
        collector.collect(tmp_path, database, output)
    assert output.read_bytes() == original
    assert "PRIVATE SENTINEL" not in str(capsys.readouterr())


def test_material_change_requires_candidate_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_git(root: Path, *args: str) -> str:
        if args[0] == "status":
            return ""
        return "src/privilab/main.py"

    monkeypatch.setattr(collector, "git", fake_git)
    with pytest.raises(ValueError, match="CANDIDATE_RESET_REQUIRED"):
        collector.execution_identity(ROOT)


def test_reopen_detects_swallowed_execution_attempt(
    captured: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    database, result = captured
    identity = result["scenarios"][0]["run_id"]
    original = collector.page

    def replaying_page(*args: Any, **kwargs: Any) -> Any:
        try:
            collector.RunService.run(None)
        except RuntimeError:
            pass
        return original(*args, **kwargs)

    monkeypatch.setattr(collector, "page", replaying_page)
    evidence = collector.reopen_evidence(
        Settings(preview_database=database), [identity]
    )
    assert evidence["persistence_unchanged"]
    assert evidence["http_statuses"] == [200, 200]
    assert evidence["guarded_execution_call_counts"]["run"] == 2
    assert not evidence["passed"]
