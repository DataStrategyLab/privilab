"""Governed untrusted source text cannot acquire control or review authority."""

import hashlib
import json
import shutil
from contextlib import closing
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from privilab.adapters.models import FixtureModelProvider
from privilab.adapters.retrieval import SQLiteFtsRetrievalProvider
from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.application import ModelRequest
from privilab.application.run_review import (
    ReviewConflict,
    ReviewDecision,
    RunReviewService,
)
from privilab.config import Settings, load_settings
from privilab.domain import ResearchResult
from privilab.evals import GateStatus, p0_task_definition
from privilab.web.preview import QUERY, STANDARD_CONTEXT, TASK_TEXT, open_preview_run

ROOT = Path(__file__).resolve().parents[2]


def test_exact_attack_text_enters_authorized_context_without_acquiring_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[ModelRequest] = []
    generate = FixtureModelProvider.generate

    def capture(self: FixtureModelProvider, request: ModelRequest) -> ResearchResult:
        observed.append(request)
        return generate(self, request)

    monkeypatch.setattr(FixtureModelProvider, "generate", capture)
    retrieve = Mock(wraps=SQLiteFtsRetrievalProvider.retrieve)
    # Preserve descriptor binding while counting each retrieval.
    monkeypatch.setattr(
        SQLiteFtsRetrievalProvider,
        "retrieve",
        lambda self, *args, **kwargs: retrieve(self, *args, **kwargs),
    )
    monkeypatch.chdir(tmp_path)
    settings = load_settings(
        {"PRIVILAB_PREVIEW_DB": str(tmp_path / "evidence.sqlite3")}
    )
    with open_preview_run(
        settings.preview_database,
        context_choice="malicious-source",
        corpus_root=settings.preview_corpus_root,
    ) as (runner, store):
        outcome, view = RunReviewService(store, store).execute(
            runner, context=STANDARD_CONTEXT, task_text=TASK_TEXT, query=QUERY
        )
        assert outcome.result is not None
        assert len(observed) == retrieve.call_count == 1
        request = observed[0]
        assert request.task_text == TASK_TEXT
        chunks = {chunk.source_id: chunk for chunk in request.source_chunks}
        payload = json.loads(
            (ROOT / "fixtures/corpus/synthetic_injection_v1.json").read_text()
        )
        assert chunks["synthetic-injection-001"].text == payload["text"]
        assert (
            chunks["synthetic-injection-001"].chunk_id
            == "synthetic-injection-chunk-001"
        )
        assert set(chunks) == {
            "synthetic-source-001",
            "synthetic-source-002",
            "synthetic-injection-001",
        }
        assert not hasattr(request, "tools")
        assert view.evaluation is not None
        assert view.evaluation.gate_status is GateStatus.BLOCK
        assert view.evaluation.rubric_id == p0_task_definition().rubric.rubric_id
        assert view.review is None
        with pytest.raises(ReviewConflict):
            RunReviewService(store, store).decide(
                view.run.run_id, ReviewDecision.APPROVE
            )
        RunReviewService(store, store).decide(view.run.run_id, ReviewDecision.REJECT)
        retained = "\n".join(store._connection.iterdump())
        for private in (
            payload["text"],
            TASK_TEXT,
            outcome.result.answer_text,
            "First caller-supplied synthetic source chunk.",
            "Second caller-supplied synthetic source chunk.",
        ):
            assert private not in retained
        assert '"query"' not in retained and '"notes"' not in retained
        assert store.get(view.run.run_id) == view.run
        assert store.get_evaluation(view.run.run_id) == view.evaluation


def test_explicit_temporary_corpus_used_after_cwd_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = tmp_path / "injected"
    shutil.copytree(ROOT / "fixtures/corpus", corpus)
    path = corpus / "synthetic_injection_v1.json"
    payload = json.loads(path.read_text())
    payload["text"] = "synthetic injected-root content marker"
    path.write_text(json.dumps(payload))
    manifest = json.loads((corpus / "manifest.json").read_text())
    record = next(
        record
        for record in manifest["records"]
        if record["id"] == "corpus.synthetic-injection.001"
    )
    record["content_hash"] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    (corpus / "manifest.json").write_text(json.dumps(manifest))
    settings = Settings(
        preview_corpus_root=corpus, preview_database=tmp_path / "preview.sqlite3"
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    generate = FixtureModelProvider.generate
    observed: list[ModelRequest] = []

    def capture(self: FixtureModelProvider, request: ModelRequest) -> ResearchResult:
        observed.append(request)
        return generate(self, request)

    monkeypatch.setattr(FixtureModelProvider, "generate", capture)
    with open_preview_run(
        settings.preview_database,
        context_choice="malicious-source",
        corpus_root=settings.preview_corpus_root,
    ) as (runner, store):
        RunReviewService(store, store).execute(
            runner, context=STANDARD_CONTEXT, task_text=TASK_TEXT, query=QUERY
        )
    assert any(chunk.text == payload["text"] for chunk in observed[0].source_chunks)
    assert list(elsewhere.iterdir()) == []


@pytest.mark.parametrize(
    "tamper",
    [
        "missing",
        "hash",
        "traversal",
        "symlink",
        "payload",
        "duplicate",
        "identity",
        "license",
    ],
)
def test_invalid_corpus_fails_without_model_or_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    corpus = tmp_path / "corpus"
    shutil.copytree(ROOT / "fixtures/corpus", corpus)
    manifest_path = corpus / "manifest.json"
    manifest: dict[str, Any] = json.loads(manifest_path.read_text())
    record = next(
        record
        for record in manifest["records"]
        if record["id"] == "corpus.synthetic-injection.001"
    )
    payload_path = corpus / "synthetic_injection_v1.json"
    if tamper == "missing":
        payload_path.unlink()
    elif tamper == "hash":
        payload_path.write_text("{}")
    elif tamper == "traversal":
        record["path"] = "fixtures/corpus/../outside.json"
    elif tamper == "symlink":
        outside = tmp_path / "outside.json"
        outside.write_bytes(payload_path.read_bytes())
        payload_path.unlink()
        payload_path.symlink_to(outside)
    elif tamper in {"payload", "identity"}:
        payload = json.loads(payload_path.read_text())
        if tamper == "payload":
            payload["synthetic"] = False
        else:
            payload["document_id"] = "synthetic-trade-notice-001"
        payload_path.write_text(json.dumps(payload))
        record["content_hash"] = (
            "sha256:" + hashlib.sha256(payload_path.read_bytes()).hexdigest()
        )
    elif tamper == "duplicate":
        manifest["records"].append(record)
    else:
        record["license_ref"] = "unregistered"
    manifest_path.write_text(json.dumps(manifest))
    generate = Mock(side_effect=AssertionError("generation forbidden"))
    monkeypatch.setattr(FixtureModelProvider, "generate", generate)
    with pytest.raises((ValueError, FileNotFoundError)):
        with open_preview_run(context_choice="malicious-source", corpus_root=corpus):
            pytest.fail("unsafe corpus accepted")
    generate.assert_not_called()


def test_run_a_cannot_supply_evaluation_or_review_for_run_b(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "preview.sqlite3"
    with open_preview_run(path) as (runner, store):
        app = RunReviewService(store, store)
        _, first = app.execute(
            runner, context=STANDARD_CONTEXT, task_text=TASK_TEXT, query=QUERY
        )
        _, second = app.execute(
            runner, context=STANDARD_CONTEXT, task_text=TASK_TEXT, query=QUERY
        )
        assert first.evaluation is not None
        monkeypatch.setattr(store, "get_evaluation", lambda run_id: first.evaluation)
        with pytest.raises(ReviewConflict):
            app.decide(second.run.run_id, ReviewDecision.APPROVE)
        assert store.get_review(second.run.run_id) is None
    with closing(SQLiteProvenanceStore(path)) as store:
        assert store.get_review(first.run.run_id) is None
        assert (
            RunReviewService(store, store).get(second.run.run_id).review_state
            == "PENDING"
        )


def test_corrupt_snapshot_is_not_repaired_and_cannot_authorize_review(
    tmp_path: Path,
) -> None:
    path = tmp_path / "preview.sqlite3"
    with open_preview_run(path) as (runner, store):
        _, view = RunReviewService(store, store).execute(
            runner, context=STANDARD_CONTEXT, task_text=TASK_TEXT, query=QUERY
        )
        trigger = store._connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE name = 'prevent_run_evaluations_update'"
        ).fetchone()[0]
        store._connection.execute("DROP TRIGGER prevent_run_evaluations_update")
        store._connection.execute(
            "UPDATE run_evaluations SET snapshot_json = '{}' WHERE run_id = ?",
            (view.run.run_id.value,),
        )
        store._connection.execute(trigger)
        store._connection.commit()
    with closing(SQLiteProvenanceStore(path)) as store:
        service = RunReviewService(store, store)
        assert service.get(view.run.run_id).review_state == "NOT REVIEWABLE"
        with pytest.raises(ReviewConflict):
            service.decide(view.run.run_id, ReviewDecision.REJECT)
        assert (
            store._connection.execute(
                "SELECT snapshot_json FROM run_evaluations"
            ).fetchone()[0]
            == "{}"
        )
        assert store.get_review(view.run.run_id) is None
