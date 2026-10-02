"""DSL-119 presentation/disclosure checks against the real fixture workflow."""

from __future__ import annotations

import asyncio
import hashlib
import re
import tomllib
from contextlib import closing
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from starlette.types import Message, Scope
from test_preview_app import add_test_sources, assert_safe_page, synthetic_source
from test_walking_skeleton import get, post

from privilab.adapters.models import FixtureModelProvider
from privilab.adapters.retrieval import SQLiteFtsRetrievalProvider
from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.application import ModelRequest, run_review
from privilab.config import Settings
from privilab.domain import CitationReference, ResearchResult
from privilab.main import STATIC_DIR, create_app
from privilab.web.presentation import SCENARIO_COPY

LOGO = "branding/DSL_primary_full-color_light-bg_1024w_v1.png"
LOGO_SHA256 = "351a2769ed240d03f178294b74b67df5a3bc95568bc26e722aba9e8d40034007"
ROOT = Path(__file__).parents[2]


@dataclass
class Element:
    tag: str
    attrs: dict[str, str | None]
    text: str = ""
    ancestors: tuple[str, ...] = ()


class Document(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__()
        self.nodes: list[Element] = []
        self.stack: list[Element] = []
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = Element(tag, dict(attrs), ancestors=tuple(n.tag for n in self.stack))
        self.nodes.append(element)
        if tag not in {"img", "meta", "link", "input", "br", "hr"}:
            self.stack.append(element)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        for node in self.stack:
            node.text += data

    def tagged(self, tag: str) -> list[Element]:
        return [node for node in self.nodes if node.tag == tag]

    def identified(self, identity: str) -> Element:
        return next(node for node in self.nodes if node.attrs.get("id") == identity)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(preview_database=tmp_path / "preview.sqlite3")


def assert_shell(html: str) -> Document:
    assert_safe_page(html)
    document = Document(html)
    for tag in ("header", "nav", "main", "h1", "footer"):
        assert len(document.tagged(tag)) == 1
    assert document.tagged("h1")[0].text.strip()
    logo = document.tagged("img")
    assert len(logo) == 1
    assert logo[0].attrs == {
        "src": "/static/" + LOGO,
        "width": "1024",
        "height": "444",
        "alt": "Data Strategy Lab",
    }
    assert document.tagged("link")[0].attrs["href"] == "/static/app.css"
    assert not document.tagged("script") and not document.tagged("style")
    for node in document.nodes:
        for attribute in ("src", "href", "action"):
            value = node.attrs.get(attribute)
            if value:
                assert value.startswith(("/", "#")) and not value.startswith("//")
        if node.tag == "th":
            assert node.attrs.get("scope") == "col"
        if node.tag == "section":
            assert "aria-labelledby" in node.attrs or "h3" in node.ancestors
    identifiers = [n.attrs["id"] for n in document.nodes if "id" in n.attrs]
    assert len(identifiers) == len(set(identifiers))
    for node in document.nodes:
        for attribute in ("aria-labelledby", "aria-describedby"):
            for reference in (node.attrs.get(attribute) or "").split():
                assert reference in identifiers
    return document


async def asset_response(app: FastAPI, path: str) -> tuple[int, bytes, bytes]:
    messages: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def send(message: Message) -> None:
        messages.append(message)

    scope = cast(
        Scope,
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "scheme": "http",
            "headers": [],
            "server": ("127.0.0.1", 8000),
        },
    )
    await app(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages)
    return start["status"], body, dict(start["headers"]).get(b"content-type", b"")


def test_local_assets_integrity_and_static_confinement(settings: Settings) -> None:
    app = create_app(settings)
    for name, mime in ((LOGO, b"image/png"), ("app.css", b"text/css")):
        status, body, content_type = asyncio.run(asset_response(app, "/static/" + name))
        assert status == 200 and content_type.startswith(mime)
        assert body == (STATIC_DIR / name).read_bytes()
        if name == LOGO:
            assert hashlib.sha256(body).hexdigest() == LOGO_SHA256
        else:
            css = body.decode()
            assert not re.search(r"https?:|@import|url\(", css)
            assert ":focus-visible" in css and "height: auto" in css
    for path in ("/static/", "/static/../templates/index.html", "/static/missing.css"):
        assert asyncio.run(asset_response(app, path))[0] == 404
    assert not settings.preview_database.exists()


def test_landing_shell_and_bounded_scenario_guide(settings: Settings) -> None:
    status, html, _ = get(create_app(settings), "/")
    assert status == 200
    # Guide headings sit within their own descriptive sections.
    document = assert_shell(html)
    assert "A reference architecture for controlled, permission-aware AI" in html
    assert [n.attrs["value"] for n in document.tagged("option")] == list(SCENARIO_COPY)
    assert document.tagged("option")[0].attrs.get("selected") is None
    assert "selected" in document.tagged("option")[0].attrs
    assert len(document.tagged("select")) == 1
    assert not document.tagged("input") and not document.tagged("textarea")
    for label, description, bounded_task in SCENARIO_COPY.values():
        assert label in html and description in html and bounded_task in html
    assert not settings.preview_database.exists()


def test_presentation_keeps_the_approved_runtime_and_no_frontend_build() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert {
        re.split(r"[<>=\[]", dependency)[0]
        for dependency in project["project"]["dependencies"]
    } == {"fastapi", "jinja2", "openai", "uvicorn"}
    for name in ("package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"):
        assert not (ROOT / name).exists()
        assert not list((ROOT / "src/privilab/web").rglob(name))
    assert not list(STATIC_DIR.rglob("*.js"))


@pytest.mark.parametrize("choice", SCENARIO_COPY)
def test_all_scenarios_share_shell_claims_and_truthful_sections(
    choice: str, settings: Settings
) -> None:
    app = create_app(settings)
    status, html, _ = post(app, "/runs", f"context_choice={choice}".encode())
    assert status == 200
    document = assert_shell(html)
    assert document.tagged("h1")[0].text == SCENARIO_COPY[choice][0]
    for label in (
        "Synthetic user",
        "Synthetic role",
        "Synthetic client",
        "Synthetic matter",
        "Synthetic workflow",
    ):
        assert label in html
    with closing(SQLiteProvenanceStore(settings.preview_database)) as store:
        view = run_review.RunReviewService(store, store).get(store.recent_run_ids()[0])
    assert view.run.status.value in document.identified("run-summary").text
    if view.run.status.value == "PERMISSION_STOPPED":
        for identity in (
            "authorized-sources",
            "research-result",
            "evaluation",
            "human-review",
        ):
            assert f'id="{identity}"' not in html
        assert not document.tagged("form")
        assert view.evaluation is not None
        assert (
            view.evaluation.gate_status.value
            in document.identified("stop-evaluation").text
        )
        assert "protected progression stopped" in html
    else:
        assert "Draft result" in html
        assert html.count("Presented for reviewer consideration.") == 1
        assert "The automated gate is separate from the human decision." in html
        controls = {n.attrs["value"]: n for n in document.tagged("button")}
        for decision in run_review.ReviewDecision:
            assert ("disabled" not in controls[decision.value].attrs) == (
                decision in view.allowed_decisions
            )
        if run_review.ReviewDecision.APPROVE not in view.allowed_decisions:
            assert (
                "Approval is unavailable"
                in document.identified("approval-explanation").text
            )
        assert "not authenticated production/client release authority" in html
    reopened = get(app, "/runs/" + view.run.run_id.value)[1]
    assert_shell(reopened)
    assert f'<h1 id="run-heading">{SCENARIO_COPY[choice][0]}</h1>' in reopened
    assert (
        'id="research-result"' not in reopened
        and 'id="draft-citations"' not in reopened
    )
    assert 'id="task-heading"' not in reopened
    assert (
        "Metadata only; generated answers and source text are not retained here."
        in reopened
    )
    assert_shell(get(app, "/runs")[1])


def test_citations_are_disclosed_only_from_original_result_without_authority_changes(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    generate = FixtureModelProvider.generate
    rejected_source = "rejected-source-PRIVATE-CANARY"
    rejected_chunk = "rejected-chunk-PRIVATE-CANARY"
    seen: list[ResearchResult] = []

    def with_rejected_citations(
        self: FixtureModelProvider, request: ModelRequest
    ) -> ResearchResult:
        result = generate(self, request)
        result = replace(
            result,
            citations=result.citations
            + (
                CitationReference(rejected_source, rejected_chunk),
                CitationReference("synthetic-source-001", rejected_chunk),
                CitationReference("synthetic-source-001", "synthetic-chunk-002"),
            ),
        )
        seen.append(result)
        return result

    monkeypatch.setattr(FixtureModelProvider, "generate", with_rejected_citations)
    app = create_app(settings)
    status, html, _ = post(app, "/runs", b"context_choice=standard")
    assert status == 200
    citations = Document(html).identified("draft-citations").text
    assert citations.count("Reference unavailable") == 3
    for citation in seen[0].citations[:2]:
        assert citation.source_id in citations and citation.chunk_id in citations
    assert rejected_source not in html and rejected_chunk not in html
    with closing(SQLiteProvenanceStore(settings.preview_database)) as store:
        identity = store.recent_run_ids()[0]
        view = run_review.RunReviewService(store, store).get(identity)
        assert len(view.run.sources) == 2
        assert (
            view.evaluation is not None and view.evaluation.gate_status.value == "BLOCK"
        )
        citation_check = next(
            c
            for c in view.evaluation.criteria
            if c.criterion_id == "citation-resolution"
        )
        assert citation_check.status.value == "FAIL"
        assert citation_check.evidence.citation_count == len(seen[0].citations)
        retained = "\n".join(store._connection.iterdump())
        assert rejected_source not in retained and rejected_chunk not in retained
    for owner, name in (
        (FixtureModelProvider, "generate"),
        (SQLiteFtsRetrievalProvider, "retrieve"),
        (run_review, "evaluate"),
    ):
        monkeypatch.setattr(owner, name, Mock(side_effect=AssertionError("no replay")))
    for path in ("/runs/" + identity.value, "/runs"):
        status, reopened, _ = get(create_app(settings), path)
        assert status == 200 and 'id="draft-citations"' not in reopened
        assert rejected_source not in reopened and rejected_chunk not in reopened


def test_authorized_citation_markup_is_escaped(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = '<script>source & "marker"</script>'
    chunk = '<script>chunk & "marker"</script>'
    add_test_sources(
        monkeypatch, synthetic_source(source, chunks=((chunk, 0, "synthetic"),))
    )
    generate = FixtureModelProvider.generate

    def markup(self: FixtureModelProvider, request: ModelRequest) -> ResearchResult:
        return replace(
            generate(self, request), citations=(CitationReference(source, chunk),)
        )

    monkeypatch.setattr(FixtureModelProvider, "generate", markup)
    status, html, _ = post(create_app(settings), "/runs", b"context_choice=standard")
    assert status == 200
    assert_safe_page(html)
    citations = Document(html).identified("draft-citations").text
    assert source in citations and chunk in citations
    assert source not in html and chunk not in html
    assert not Document(html).tagged("script")


@pytest.mark.parametrize("decision", ["APPROVE", "REJECT", "REQUEST_REVISION"])
def test_review_labels_final_explanation_and_history(
    settings: Settings, decision: str
) -> None:
    app = create_app(settings)
    html = post(app, "/runs", b"context_choice=standard")[1]
    document = assert_shell(html)
    assert [n.text for n in document.tagged("button")] == [
        "Approve",
        "Reject",
        "Request revision",
    ]
    with closing(SQLiteProvenanceStore(settings.preview_database)) as store:
        identity = store.recent_run_ids()[0]
    path = "/runs/" + identity.value
    assert post(app, path + "/review", f"decision={decision}".encode())[0] == 303
    reviewed = assert_shell(get(app, path)[1])
    assert (
        "final decision is already recorded"
        in reviewed.identified("approval-explanation").text
    )
    assert all("disabled" in n.attrs for n in reviewed.tagged("button"))
    assert decision in reviewed.identified("human-review").text
    assert decision in assert_shell(get(app, "/runs")[1]).tagged("main")[0].text


def test_empty_history_and_invalid_request_remain_claims_safe(
    settings: Settings,
) -> None:
    app = create_app(settings)
    assert (
        "No runs recorded." in assert_shell(get(app, "/runs")[1]).tagged("main")[0].text
    )
    status, html, _ = post(app, "/runs", b"context_choice=untrusted-PRIVATE-CANARY")
    assert status == 400 and "PRIVATE-CANARY" not in html
    assert_safe_page(html)
    assert any(n.attrs.get("role") == "alert" for n in Document(html).nodes)
    assert not settings.preview_database.exists()
