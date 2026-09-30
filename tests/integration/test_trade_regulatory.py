"""Execute the actual governed chain and reconstruct task identity without bodies."""

from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from test_walking_skeleton import get, post

from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.application.provenance import governed_configuration_hash
from privilab.application.run_review import (
    ReviewConflict,
    ReviewDecision,
    RunReviewService,
)
from privilab.application.trade_regulatory_tasks import TASK_CHOICES, load_task_pack
from privilab.config import Settings
from privilab.evals.trade_regulatory import (
    observed,
    open_task_run,
    run_golden,
    task_policy,
)
from privilab.main import create_app

ROOT = Path(__file__).resolve().parents[2]


def test_all_golden_cases_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    monkeypatch.setattr(
        socket,
        "create_connection",
        Mock(side_effect=AssertionError("network forbidden")),
    )
    outcomes = run_golden(ROOT)
    assert len(outcomes) == 6 and all(matched for _, matched in outcomes)


@pytest.mark.parametrize("task_id", [key for key, _ in TASK_CHOICES])
def test_persisted_evidence_and_review(tmp_path: Path, task_id: str) -> None:
    database = tmp_path / "provenance.sqlite3"
    with open_task_run(ROOT, task_id, database_path=database) as (task, service, store):
        outcome, view = RunReviewService(store, store).execute(
            service, context=task.context, task_text=task.task_text, query=task.query
        )
        assert observed(view) == task.expected.as_dict()
        assert view.review is None
        assert view.run.configuration.options == task.configuration_options
        assert view.run.configuration_hash == governed_configuration_hash(
            view.run.configuration, task_policy()
        )
        for name, value in task.configuration_options:
            changed = dict(task.configuration_options) | {name: value + "-changed"}
            config = replace(view.run.configuration, options=tuple(changed.items()))
            assert (
                governed_configuration_hash(config, task_policy())
                != view.run.configuration_hash
            )
        retained = "\n".join(store._connection.iterdump())
        assert task.task_text not in retained
        assert '"query"' not in retained
        if outcome.result:
            assert outcome.result.answer_text not in retained
        assert (
            "Synthetic notice text for fixture and provenance validation only."
            not in retained
        )
    with closing(SQLiteProvenanceStore(database)) as reopened:
        reviews = RunReviewService(reopened, reopened)
        restored = reviews.get(outcome.run_id)
        assert restored == view
        assert (
            load_task_pack(ROOT).select(
                dict(restored.run.configuration.options)["domain_task_id"]
            )
            == task
        )
        if "APPROVE" not in task.expected.allowed_decisions:
            with pytest.raises(ReviewConflict):
                reviews.decide(outcome.run_id, ReviewDecision.APPROVE)
        for decision in ReviewDecision:
            if decision.value not in task.expected.allowed_decisions:
                with pytest.raises(ReviewConflict):
                    reviews.decide(outcome.run_id, decision)
        if task.expected.allowed_decisions:
            reviews.decide(outcome.run_id, ReviewDecision.REJECT)
            assert reviews.get(outcome.run_id).review_state == "REJECT"


def test_insufficient_source_is_bounded_to_supplied_source() -> None:
    with open_task_run(ROOT, "trade-regulatory.insufficient-source") as (
        task,
        service,
        store,
    ):
        outcome, view = RunReviewService(store, store).execute(
            service, context=task.context, task_text=task.task_text, query=task.query
        )
        assert outcome.result
        text = outcome.result.answer_text
        assert (
            "The supplied source does not establish a licensing requirement or penalty."
            in text
        )
        assert "obtain appropriate authority and qualified substantive review" in text
        assert "no licensing requirement exists" not in text.lower()
        assert observed(view)["gate"] == "PASS"
        assert not task.prospect_demo_eligible


@pytest.mark.parametrize(
    "suffix,gate,state",
    [
        ("grounded-happy-path", "PASS", "PENDING"),
        ("permission-block", "BLOCK", "NOT REVIEWABLE"),
        ("citation-grounding-challenge", "BLOCK", "PENDING"),
    ],
)
def test_existing_preview_selector_runs_domain_tasks(
    tmp_path: Path, suffix: str, gate: str, state: str
) -> None:
    settings = Settings(preview_database=tmp_path / "preview.sqlite3")
    app = create_app(settings)
    status, html, _ = post(
        app, "/runs", f"context_choice=trade-regulatory.{suffix}".encode()
    )
    assert status == 200
    assert gate in html and state in html and "DRAFT" in html
    assert f"trade-regulatory.{suffix}" in html
    with closing(SQLiteProvenanceStore(settings.preview_database)) as store:
        identity = store.recent_run_ids()[0]
    status, reopened, _ = get(create_app(settings), "/runs/" + identity.value)
    assert status == 200 and f"trade-regulatory.{suffix}" in reopened
    assert 'class="answer"' not in reopened


def test_startup_and_existing_preview_do_not_read_task_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.read_text

    def guarded(path: Path, *args: Any, **kwargs: Any) -> str:
        if "tasks" in path.parts or "evals" in path.parts:
            raise AssertionError("startup must not read task/eval artifacts")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    settings = Settings(
        preview_database=tmp_path / "preview.sqlite3",
        preview_corpus_root=tmp_path / "fixtures/corpus",
    )
    app = create_app(settings)
    assert get(app, "/")[0] == 200
    assert post(app, "/runs", b"context_choice=standard")[0] == 200
    with closing(SQLiteProvenanceStore(settings.preview_database)) as store:
        identity = store.recent_run_ids()[0]
    assert get(create_app(settings), "/runs/" + identity.value)[0] == 200
    assert (
        post(app, "/runs", b"context_choice=trade-regulatory.grounded-happy-path")[0]
        == 500
    )


def test_container_shaped_startup_without_repository_artifacts(tmp_path: Path) -> None:
    import os
    import shutil
    import subprocess
    import sys

    shutil.copytree(
        ROOT / "src", tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copytree(ROOT / "fixtures/corpus", tmp_path / "fixtures/corpus")
    script = "\n".join(
        (
            "from pathlib import Path",
            "import privilab.main",
            "from privilab.web.preview import (open_preview_run, STANDARD_CONTEXT, "
            "TASK_TEXT, QUERY)",
            "from privilab.application.run_review import RunReviewService",
            "assert Path(privilab.main.__file__).resolve().is_relative_to(Path.cwd())",
            "assert not Path('tasks').exists() and not Path('evals').exists()",
            "assert privilab.main.app is not None",
            "with open_preview_run() as (service, store):",
            "    _, view = RunReviewService(store, store).execute(service, "
            "context=STANDARD_CONTEXT, task_text=TASK_TEXT, query=QUERY)",
            "    assert view.evaluation.gate_status.value == 'PASS'",
        )
    )
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=dict(os.environ) | {"PYTHONPATH": str(tmp_path / "src")},
        check=True,
        capture_output=True,
        text=True,
    )
