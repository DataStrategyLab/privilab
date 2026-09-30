from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from dataclasses import dataclass, field, replace
from html import escape
from pathlib import Path
from typing import NoReturn, cast
from urllib.parse import urlencode

import pytest
import yaml
from fastapi import FastAPI
from starlette.types import Message, Receive, Scope, Send

from privilab import main as web_module
from privilab.adapters.models import FixtureModelProvider
from privilab.adapters.retrieval import SQLiteFtsRetrievalProvider
from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.application import (
    FailureStage,
    ModelRequest,
    PermissionStopReason,
    RunId,
    RunProvenance,
    RunStatus,
)
from privilab.application import run_service as run_module
from privilab.config import Settings
from privilab.domain import (
    AccessScope,
    ChunkId,
    CitationReference,
    PermissionState,
    ResearchResult,
    RetrievalChunk,
    RetrievalSource,
    RetrievedChunk,
    SourceEntitlement,
    SourceId,
    SyntheticRequestContext,
)
from privilab.main import create_app
from privilab.web import preview as preview_module
from privilab.web.preview import (
    CONTEXT_CHOICES,
    PREVIEW_VERSION,
    QUERY,
    STANDARD_CONTEXT,
    TASK_TEXT,
)

ROOT = Path(__file__).parents[2]
BANNER = "Synthetic/reference demo only"
REVIEWER_PHRASE = "Presented for reviewer consideration."
INTERNAL_DIAGNOSTIC = (
    "synthetic-internal-marker /private/preview/data.sqlite3 "
    "sqlite3.OperationalError SELECT source_text "
    "synthetic-credential-marker synthetic-source-content-marker"
)
FORBIDDEN_CLAIMS = (
    "legal advice",
    "attorney work product",
    "privilege determination",
    "compliance certification",
    "client approval",
    "guaranteed confidentiality",
    "guaranteed security",
    "production ready",
    "production-ready",
    "evaluation passed",
    "critical gate passed",
    "human approved",
    "human approval",
    "release approved",
    "release approval",
)


@pytest.fixture(autouse=True)
def preview_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings(preview_database=tmp_path / "preview.sqlite3")
    monkeypatch.setattr(web_module, "load_settings", lambda: settings)
    return settings


async def request_page(
    app: FastAPI,
    *,
    method: str = "GET",
    path: str = "/",
    chunks: tuple[bytes, ...] = (b"",),
    content_type: bytes = b"application/x-www-form-urlencoded",
) -> tuple[int, str]:
    """Exercise the ASGI boundary without another HTTP client dependency."""
    messages: list[Message] = []
    chunk_index = 0

    async def receive() -> Message:
        nonlocal chunk_index
        if chunk_index == len(chunks):
            return {"type": "http.disconnect"}
        body = chunks[chunk_index]
        chunk_index += 1
        return {
            "type": "http.request",
            "body": body,
            "more_body": chunk_index < len(chunks),
        }

    async def send(message: Message) -> None:
        messages.append(message)

    scope = cast(
        Scope,
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"127.0.0.1"), (b"content-type", content_type)],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 8000),
        },
    )
    await app(scope, cast(Receive, receive), cast(Send, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    assert (b"content-type", b"text/html; charset=utf-8") in start["headers"]
    response_body = b"".join(
        cast(bytes, m.get("body", b""))
        for m in messages
        if m["type"] == "http.response.body"
    )
    return cast(int, start["status"]), response_body.decode("utf-8")


def submit(choice: str = "standard", *, app: FastAPI | None = None) -> tuple[int, str]:
    return asyncio.run(
        request_page(
            app or create_app(),
            method="POST",
            path="/runs",
            chunks=(urlencode({"context_choice": choice}).encode(),),
        )
    )


def assert_safe_page(html: str) -> None:
    assert BANNER in html
    assert INTERNAL_DIAGNOSTIC not in html
    for sentinel in INTERNAL_DIAGNOSTIC.split():
        assert sentinel not in html
    assert "Traceback" not in html
    assert "<script" not in html.lower()
    for claim in FORBIDDEN_CLAIMS:
        assert claim not in html.lower()


def assert_no_later_sections(html: str) -> None:
    assert 'id="authorized-sources"' not in html
    assert 'id="research-result"' not in html
    assert REVIEWER_PHRASE not in html


def fail(*args: object, **kwargs: object) -> NoReturn:
    raise RuntimeError(INTERNAL_DIAGNOSTIC)


@dataclass
class RunEvidence:
    queries: list[str] = field(default_factory=list)
    retrieved: list[tuple[RetrievedChunk, ...]] = field(default_factory=list)
    requests: list[ModelRequest] = field(default_factory=list)
    records: list[RunProvenance] = field(default_factory=list)
    lookups: list[RunId] = field(default_factory=list)
    closes: list[str] = field(default_factory=list)


@pytest.fixture
def evidence(monkeypatch: pytest.MonkeyPatch) -> RunEvidence:
    observed = RunEvidence()
    retrieve = SQLiteFtsRetrievalProvider.retrieve
    generate = FixtureModelProvider.generate
    append = SQLiteProvenanceStore.append
    get = SQLiteProvenanceStore.get
    close_retrieval = SQLiteFtsRetrievalProvider.close
    close_store = SQLiteProvenanceStore.close

    def retrieve_spy(
        self: SQLiteFtsRetrievalProvider,
        query: str,
        access_scope: AccessScope,
        *,
        limit: int = 10,
    ) -> tuple[RetrievedChunk, ...]:
        observed.queries.append(query)
        chunks = retrieve(self, query, access_scope, limit=limit)
        observed.retrieved.append(chunks)
        return chunks

    def generate_spy(
        self: FixtureModelProvider, request: ModelRequest
    ) -> ResearchResult:
        observed.requests.append(request)
        return generate(self, request)

    def append_spy(self: SQLiteProvenanceStore, record: RunProvenance) -> None:
        append(self, record)
        observed.records.append(record)

    def get_spy(self: SQLiteProvenanceStore, run_id: RunId) -> RunProvenance | None:
        observed.lookups.append(run_id)
        return get(self, run_id)

    def close_retrieval_spy(self: SQLiteFtsRetrievalProvider) -> None:
        close_retrieval(self)
        observed.closes.append("retrieval")

    def close_store_spy(self: SQLiteProvenanceStore) -> None:
        close_store(self)
        observed.closes.append("provenance")

    monkeypatch.setattr(SQLiteFtsRetrievalProvider, "retrieve", retrieve_spy)
    monkeypatch.setattr(FixtureModelProvider, "generate", generate_spy)
    monkeypatch.setattr(SQLiteProvenanceStore, "append", append_spy)
    monkeypatch.setattr(SQLiteProvenanceStore, "get", get_spy)
    monkeypatch.setattr(SQLiteFtsRetrievalProvider, "close", close_retrieval_spy)
    monkeypatch.setattr(SQLiteProvenanceStore, "close", close_store_spy)
    return observed


def test_new_run_page_has_only_the_controlled_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preview_module, "SQLiteFtsRetrievalProvider", fail)
    monkeypatch.setattr(preview_module, "SQLiteProvenanceStore", fail)
    status, html = asyncio.run(request_page(create_app()))

    assert status == 200
    assert_safe_page(html)
    assert_no_later_sections(html)
    assert 'id="run-detail"' not in html
    assert "bootstrap placeholder" not in html
    assert TASK_TEXT in html and QUERY in html
    assert 'method="post" action="/runs"' in html
    assert re.findall(r'<option value="([^"]+)"', html) == [
        "standard",
        "blocked-role",
        "missing-workflow",
        "conditional-role",
        "critical-citation-failure",
        "malicious-source",
        "trade-regulatory.grounded-happy-path",
        "trade-regulatory.insufficient-source",
        "trade-regulatory.permission-block",
        "trade-regulatory.critical-eval-failure",
        "trade-regulatory.citation-grounding-challenge",
        "trade-regulatory.malicious-source-injection",
    ]
    assert re.findall(r'<(?:input|select|textarea)[^>]*name="([^"]+)"', html) == [
        "context_choice"
    ]
    assert "Simulated context controls" in html
    assert "fixed synthetic fixture answer" in html


def test_import_does_not_open_adapters() -> None:
    script = "\n".join(
        (
            "from unittest.mock import patch",
            "with patch('privilab.adapters.retrieval.SQLiteFtsRetrievalProvider', "
            "side_effect=AssertionError('unexpected adapter')), "
            "patch('privilab.adapters.storage.SQLiteProvenanceStore', "
            "side_effect=AssertionError('unexpected adapter')):",
            "    import privilab.main",
        )
    )
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True)


def test_preview_context_and_synthetic_registration_match_approved_inputs() -> None:
    payload = (ROOT / "fixtures/contexts/synthetic_request_context_v1.json").read_text()
    assert STANDARD_CONTEXT == SyntheticRequestContext.from_json(payload)
    contexts = {key: context for key, _label, context in CONTEXT_CHOICES}
    assert contexts["standard"] == STANDARD_CONTEXT
    assert contexts["missing-workflow"] == replace(STANDARD_CONTEXT, workflow=None)
    for key, expected_role in (
        ("blocked-role", "synthetic-blocked"),
        ("conditional-role", "synthetic-conditional"),
    ):
        context = contexts[key]
        assert replace(context, user=STANDARD_CONTEXT.user) == STANDARD_CONTEXT
        assert context.user is not None and STANDARD_CONTEXT.user is not None
        assert context.user.identity == STANDARD_CONTEXT.user.identity
        assert context.user.role is not None
        assert context.user.role.role_id == expected_role
        assert context.synthetic is True
    entries = yaml.safe_load((ROOT / "licenses/registry.yaml").read_text())
    registered = [e for e in entries if e["id"] == "fixture:synthetic-preview"]
    assert len(registered) == 1
    entry = registered[0]
    assert entry["kind"] == "fixture"
    assert entry["version_or_commit"] == PREVIEW_VERSION == "1.1.0"
    assert entry["repository_paths"] == ["src/privilab/web/preview.py"]
    assert "Repository-authored" in entry["permitted_use_basis"]
    assert "Synthetic demonstration content only" in entry["restrictions"]


@pytest.mark.parametrize(
    ("choice", "state", "reason", "conditions"),
    [
        ("blocked-role", PermissionState.BLOCK, PermissionStopReason.BLOCK, ()),
        ("missing-workflow", PermissionState.UNKNOWN, PermissionStopReason.UNKNOWN, ()),
        (
            "conditional-role",
            PermissionState.CONDITIONAL,
            PermissionStopReason.UNRESOLVED_CONDITIONS,
            ("condition-synthetic-001",),
        ),
    ],
)
def test_permission_stops_prevent_all_later_progression(
    choice: str,
    state: PermissionState,
    reason: PermissionStopReason,
    conditions: tuple[str, ...],
    evidence: RunEvidence,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A stopped route must not even ask for a protected access scope.
    scope_calls: list[bool] = []

    def unexpected_scope(*args: object, **kwargs: object) -> NoReturn:
        scope_calls.append(True)
        fail()

    monkeypatch.setattr(run_module, "access_scope_for", unexpected_scope)
    status, html = submit(choice)
    assert status == 200
    assert_safe_page(html)
    assert_no_later_sections(html)
    assert f"Permission: <strong>{state.value}</strong>" in html
    assert "protected progression stopped" in html
    assert reason.value in html
    assert "Retrieval: not executed." in html
    assert "Model: not executed." in html
    assert scope_calls == []
    assert evidence.queries == []
    assert evidence.requests == []
    assert len(evidence.records) == 1
    record = evidence.records[0]
    assert record.status is RunStatus.PERMISSION_STOPPED
    assert record.stop_reason is reason
    assert record.permission is not None
    assert record.permission.unresolved_condition_ids == conditions
    for condition in conditions:
        assert condition in html
    assert record.sources == ()
    assert record.retrieval_called is record.model_called is False
    assert evidence.lookups == [record.run_id]
    assert record.run_id.value in html
    assert evidence.closes == ["provenance", "retrieval"]


def test_generated_run_uses_governed_fixture_and_trusted_provenance(
    evidence: RunEvidence,
) -> None:
    status, html = submit()
    assert status == 200
    assert_safe_page(html)
    assert html.count(REVIEWER_PHRASE) == 1
    assert 'id="authorized-sources"' in html
    assert 'id="research-result"' in html
    assert "Permission: <strong>ALLOW</strong>" in html
    assert evidence.queries == [QUERY]
    assert len(evidence.requests) == len(evidence.records) == 1
    request = evidence.requests[0]
    assert request.task_text == TASK_TEXT
    record = evidence.records[0]
    assert record.status is RunStatus.GENERATED
    assert record.retrieval_called is record.model_called is True
    assert evidence.lookups == [record.run_id]
    assert evidence.closes == ["provenance", "retrieval"]
    fixture_path = ROOT / (
        "src/privilab/adapters/models/resources/governed_fixtures/"
        "synthetic_happy_path_v1.json"
    )
    result = ResearchResult.from_json(fixture_path.read_text())
    assert result.answer_text in html
    source_pairs = {
        (chunk.source_id, chunk.chunk_id) for chunk in request.source_chunks
    }
    assert (
        source_pairs
        == {
            ("synthetic-source-001", "synthetic-chunk-001"),
            ("synthetic-source-002", "synthetic-chunk-002"),
        }
        == {(citation.source_id, citation.chunk_id) for citation in result.citations}
    )
    rows = record.chunks_in_retrieval_order
    assert [(s, c.chunk_id) for s, _v, c in rows] == [
        (c.source_id, c.chunk_id) for c in request.source_chunks
    ]
    for source_id, version, chunk in rows:
        assert version == PREVIEW_VERSION
        assert (
            f"<tr><td>{source_id}</td><td>{version}</td><td>{chunk.chunk_id}</td>"
            f"<td>{chunk.ordinal}</td><td>{chunk.retrieval_position}</td></tr>"
        ) in html
    for supplied_chunk in request.source_chunks:
        assert supplied_chunk.text not in html
    for value in (
        record.run_id.value,
        record.started_at.isoformat(),
        record.completed_at.isoformat(),
        "synthetic-user-001",
        "synthetic-researcher",
        "synthetic-client-001",
        "synthetic-matter-001",
        "synthetic-workflow-001",
        "policy.synthetic-preview.001",
        "p0-synthetic-preview",
        "fixture-model-provider",
        "model-output.synthetic-happy-path.001",
        record.configuration_hash,
    ):
        assert value in html
    assert "Configured model" in html


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"context_choice=",
        b"context_choice=unknown",
        b"context_choice=standard&context_choice=blocked-role",
        b"context_choice=standard&task_text=override",
        b"context_choice=standard&query=override",
        b"context_choice=standard&policy=ALLOW",
        b"context_choice=standard&satisfied_conditions=condition-synthetic-001",
        b"context_choice",
        b"context_choice=standard&",
        b"context_choice=%",
        b"context_choice=%GG",
        b"context_choice=%FF",
        b"context_choice=\xff",
        b"context_choice=%ED%A0%80",
        b"context_choice=%00standard",
        b"context_choice=<script>bad-input</script>",
        b"context_choice=" + b"x" * 1024,
    ],
)
def test_invalid_forms_never_start_composition(
    body: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_module, "open_preview_run", fail)
    status, html = asyncio.run(
        request_page(
            create_app(),
            method="POST",
            path="/runs",
            chunks=(body,),
        )
    )
    assert status == 400
    assert_safe_page(html)
    assert_no_later_sections(html)
    assert "Select a listed synthetic context" in html
    assert "bad-input" not in html


@pytest.mark.parametrize(
    "content_type", [b"", b"application/json", b"multipart/form-data"]
)
def test_unsupported_media_type_is_a_safe_form_error(content_type: bytes) -> None:
    status, html = asyncio.run(
        request_page(
            create_app(),
            method="POST",
            path="/runs",
            chunks=(b"context_choice=standard",),
            content_type=content_type,
        )
    )
    assert status == 400
    assert_safe_page(html)
    assert_no_later_sections(html)


def test_streamed_form_limit_is_enforced_before_execution(
    evidence: RunEvidence,
) -> None:
    status, html = asyncio.run(
        request_page(
            create_app(),
            method="POST",
            path="/runs",
            chunks=(b"context_choice=standard", b"x" * 1002),
        )
    )
    assert status == 400
    assert_safe_page(html)
    assert evidence.queries == []
    assert evidence.requests == []
    assert evidence.records == []
    assert evidence.closes == []


def test_valid_percent_encoded_chunked_form(evidence: RunEvidence) -> None:
    status, html = asyncio.run(
        request_page(
            create_app(),
            method="POST",
            path="/runs",
            chunks=(b"context_", b"choice=stand%61rd"),
            content_type=b"application/x-www-form-urlencoded; charset=UTF-8",
        )
    )
    assert status == 200
    assert_safe_page(html)
    assert len(evidence.records) == 1


def synthetic_source(
    source_value: str,
    *,
    user_id: str | None = "synthetic-user-001",
    version: str = "1.0.0",
    chunks: tuple[tuple[str, int, str], ...] | None = None,
) -> RetrievalSource:
    source_id = SourceId(source_value)
    return RetrievalSource(
        source_id=source_id,
        source_version=version,
        title="Synthetic test source",
        chunks=tuple(
            RetrievalChunk(ChunkId(chunk_id), source_id, ordinal, text)
            for chunk_id, ordinal, text in (
                chunks
                if chunks is not None
                else ((f"{source_value}.chunk", 0, "synthetic test source text"),)
            )
        ),
        entitlements=()
        if user_id is None
        else (
            SourceEntitlement(
                source_id,
                user_id,
                "synthetic-researcher",
                "synthetic-client-001",
                "synthetic-matter-001",
                "synthetic-workflow-001",
            ),
        ),
    )


def add_test_sources(
    monkeypatch: pytest.MonkeyPatch,
    *sources: RetrievalSource,
) -> None:
    def seeded_provider(database_path: str | Path) -> SQLiteFtsRetrievalProvider:
        provider = SQLiteFtsRetrievalProvider(database_path)
        try:
            for source in sources:
                provider.index_source(source)
        except BaseException:
            provider.close()
            raise
        return provider

    monkeypatch.setattr(preview_module, "SQLiteFtsRetrievalProvider", seeded_provider)


def test_unauthorized_sources_never_reach_model_provenance_or_html(
    evidence: RunEvidence,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other_context = synthetic_source(
        "synthetic-other-context",
        user_id="synthetic-other-user",
        chunks=(("synthetic-other-chunk", 0, "synthetic excluded-other-context-text"),),
    )
    unentitled = synthetic_source(
        "synthetic-unentitled",
        user_id=None,
        chunks=(
            ("synthetic-unentitled-chunk", 0, "synthetic excluded-unentitled-text"),
        ),
    )
    add_test_sources(monkeypatch, other_context, unentitled)
    status, html = submit()
    assert status == 200
    assert_safe_page(html)
    assert len(evidence.queries) == len(evidence.requests) == 1
    assert len(evidence.requests[0].source_chunks) == 2
    assert len(evidence.records[0].sources) == 2
    for source in (other_context, unentitled):
        assert source.source_id.value not in html
        for chunk in source.chunks:
            assert chunk.chunk_id.value not in html and chunk.text not in html
            assert all(
                delivered.source_id != source.source_id.value
                and delivered.chunk_id != chunk.chunk_id.value
                and delivered.text != chunk.text
                for delivered in evidence.requests[0].source_chunks
            )
        assert all(
            recorded.source_id != source.source_id.value
            for recorded in evidence.records[0].sources
        )


def test_model_citations_cannot_add_authorized_source_rows(
    evidence: RunEvidence,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generate = FixtureModelProvider.generate

    def extra_citation(
        self: FixtureModelProvider, request: ModelRequest
    ) -> ResearchResult:
        result = generate(self, request)
        return replace(
            result,
            citations=result.citations
            + (
                CitationReference(
                    "synthetic-citation-only-source", "citation-only-chunk"
                ),
            ),
        )

    monkeypatch.setattr(FixtureModelProvider, "generate", extra_citation)
    status, html = submit()
    assert status == 200
    assert "synthetic-citation-only-source" not in html
    assert "citation-only-chunk" not in html
    assert len(evidence.records[0].sources) == 2
    assert "synthetic-source-001" in html and "synthetic-source-002" in html


def test_display_preserves_interleaved_retrieval_order(
    evidence: RunEvidence,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_test_sources(
        monkeypatch,
        synthetic_source(
            "synthetic-order-a",
            version="2.0.0",
            chunks=(
                ("order-a-first", 3, "synthetic"),
                (
                    "order-a-last",
                    7,
                    "synthetic synthetic padding padding padding padding",
                ),
            ),
        ),
        synthetic_source(
            "synthetic-order-b",
            version="3.0.0",
            chunks=(("order-b-middle", 9, "synthetic padding"),),
        ),
    )
    status, html = submit()
    assert status == 200
    rows = evidence.records[0].chunks_in_retrieval_order
    assert [source for source, _version, _chunk in rows[:3]] == [
        "synthetic-order-a",
        "synthetic-order-b",
        "synthetic-order-a",
    ]
    offsets = []
    for source_id, version, chunk in rows:
        row = (
            f"<tr><td>{source_id}</td><td>{version}</td><td>{chunk.chunk_id}</td>"
            f"<td>{chunk.ordinal}</td><td>{chunk.retrieval_position}</td></tr>"
        )
        offsets.append(html.index(row))
    assert offsets == sorted(offsets)


@pytest.mark.parametrize("stage", list(FailureStage))
def test_stage_failures_are_safely_rendered_from_real_service_outcomes(
    stage: FailureStage,
    evidence: RunEvidence,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure_calls: list[bool] = []

    def injected_failure(*args: object, **kwargs: object) -> NoReturn:
        failure_calls.append(True)
        fail()

    if stage is FailureStage.PERMISSION:
        monkeypatch.setattr(run_module, "evaluate_permission", injected_failure)
    elif stage is FailureStage.AUTHORIZATION:
        monkeypatch.setattr(run_module, "access_scope_for", injected_failure)
    elif stage is FailureStage.RETRIEVAL:
        monkeypatch.setattr(SQLiteFtsRetrievalProvider, "retrieve", injected_failure)
    else:
        monkeypatch.setattr(FixtureModelProvider, "generate", injected_failure)
    status, html = submit()
    assert status == 500
    assert_safe_page(html)
    assert_no_later_sections(html)
    assert f"Run failed during {stage.value}" in html
    assert failure_calls == [True]
    assert len(evidence.records) == 1
    record = evidence.records[0]
    assert record.status is RunStatus.FAILED
    assert record.failure_stage is stage
    expected_calls = {
        FailureStage.PERMISSION: (False, False),
        FailureStage.AUTHORIZATION: (False, False),
        FailureStage.RETRIEVAL: (True, False),
        FailureStage.MODEL: (True, True),
    }[stage]
    assert (record.retrieval_called, record.model_called) == expected_calls
    for label, called in zip(("Retrieval", "Model"), expected_calls, strict=True):
        assert f"{label}: {'called' if called else 'not executed'}." in html
    if stage is FailureStage.PERMISSION:
        assert record.permission is None
        assert "No completed decision" in html
    else:
        assert record.permission is not None
        assert record.permission.state is PermissionState.ALLOW
        assert "Permission: <strong>ALLOW</strong>" in html
    if stage is FailureStage.MODEL:
        assert len(evidence.queries) == 1
        assert len(record.sources) == 2
        assert "synthetic-source-001" not in html
    else:
        assert evidence.requests == []
    assert evidence.closes == ["provenance", "retrieval"]


@pytest.mark.parametrize(
    "failure", ["missing", "read", "append", "execution", "render"]
)
def test_unexpected_run_failures_hide_results_and_close_adapters(
    failure: str,
    evidence: RunEvidence,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if failure == "missing":

        def missing(self: SQLiteProvenanceStore, run_id: RunId) -> None:
            return None

        monkeypatch.setattr(SQLiteProvenanceStore, "get", missing)
    elif failure == "read":
        monkeypatch.setattr(SQLiteProvenanceStore, "get", fail)
    elif failure == "append":
        monkeypatch.setattr(SQLiteProvenanceStore, "append", fail)
    elif failure == "execution":
        monkeypatch.setattr(run_module.RunService, "run", fail)
    else:
        monkeypatch.setattr(web_module.templates, "TemplateResponse", fail)
    status, html = submit()
    assert status == 500
    assert_safe_page(html)
    assert_no_later_sections(html)
    assert 'id="run-detail"' not in html
    assert "Preview unavailable" in html
    assert 'href="/"' in html
    assert "synthetic-source-001" not in html
    assert evidence.closes == ["provenance", "retrieval"]


@pytest.mark.parametrize(
    ("failure", "expected_closes"),
    [
        ("retrieval-construction", []),
        ("provenance-construction", ["retrieval"]),
        ("seeding", ["provenance", "retrieval"]),
        ("governed-fixture", ["provenance", "retrieval"]),
    ],
)
def test_partial_composition_failures_close_every_opened_adapter(
    failure: str,
    expected_closes: list[str],
    evidence: RunEvidence,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if failure == "retrieval-construction":
        monkeypatch.setattr(preview_module, "SQLiteFtsRetrievalProvider", fail)
    elif failure == "provenance-construction":
        monkeypatch.setattr(preview_module, "SQLiteProvenanceStore", fail)
    elif failure == "seeding":
        monkeypatch.setattr(SQLiteFtsRetrievalProvider, "index_source", fail)
    else:
        monkeypatch.setattr(run_module.RunService, "from_governed_fixture", fail)
    status, html = submit()
    assert status == 500
    assert_safe_page(html)
    assert_no_later_sections(html)
    assert evidence.closes == expected_closes
    assert evidence.queries == []
    assert evidence.requests == []
    assert evidence.records == []


def test_template_failure_on_get_has_a_safe_labeled_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_module.templates, "TemplateResponse", fail)
    status, html = asyncio.run(request_page(create_app()))
    assert status == 500
    assert_safe_page(html)
    assert_no_later_sections(html)
    assert 'href="/"' in html


def test_answer_and_trusted_metadata_are_html_escaped(
    evidence: RunEvidence,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id = "<script>synthetic-metadata</script>"
    chunk_id = "<script>synthetic-chunk</script>"
    answer = "<script>synthetic-answer</script> & fixture"
    add_test_sources(
        monkeypatch,
        synthetic_source(
            source_id,
            chunks=((chunk_id, 0, "synthetic markup source text"),),
        ),
    )
    generate = FixtureModelProvider.generate

    def markup_answer(
        self: FixtureModelProvider, request: ModelRequest
    ) -> ResearchResult:
        return replace(generate(self, request), answer_text=answer)

    monkeypatch.setattr(FixtureModelProvider, "generate", markup_answer)
    status, html = submit()
    assert status == 200
    assert_safe_page(html)
    for raw in (source_id, chunk_id, answer):
        assert raw not in html
        assert escape(raw) in html
    assert "synthetic markup source text" not in html
    assert len(evidence.records[0].sources) == 3


def test_repeated_requests_persist_evidence_with_transient_fts_independent_of_cwd(
    evidence: RunEvidence,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths: list[str | Path] = []
    retrieval_init = SQLiteFtsRetrievalProvider.__init__
    provenance_init = SQLiteProvenanceStore.__init__

    def init_retrieval(
        self: SQLiteFtsRetrievalProvider, database_path: str | Path
    ) -> None:
        paths.append(database_path)
        retrieval_init(self, database_path)

    def init_store(self: SQLiteProvenanceStore, database_path: str | Path) -> None:
        paths.append(database_path)
        provenance_init(self, database_path)

    monkeypatch.setattr(SQLiteFtsRetrievalProvider, "__init__", init_retrieval)
    monkeypatch.setattr(SQLiteProvenanceStore, "__init__", init_store)
    monkeypatch.chdir(tmp_path)
    app = create_app()
    first_status, first_html = submit(app=app)
    second_status, second_html = submit(app=app)
    stopped_status, stopped_html = submit("blocked-role", app=app)
    assert first_status == second_status == stopped_status == 200
    assert len(evidence.records) == 3
    first, second, stopped = evidence.records
    assert len({record.run_id for record in evidence.records}) == 3
    assert first.sources == second.sources
    assert first.configuration_hash == second.configuration_hash
    assert evidence.requests[0] == evidence.requests[1]
    assert first.run_id.value not in second_html
    assert second.run_id.value not in first_html
    assert first.run_id.value not in stopped_html
    assert stopped.sources == ()
    assert_no_later_sections(stopped_html)
    assert paths == [":memory:", tmp_path / "preview.sqlite3"] * 3
    assert evidence.closes == ["provenance", "retrieval"] * 3
    assert {path.name for path in tmp_path.iterdir()} == {"preview.sqlite3"}
