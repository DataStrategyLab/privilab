from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from privilab.adapters.models import FixtureModelProvider
from privilab.application.model_provider import (
    MalformedModelOutputError,
    ModelRequest,
    ModelSourceChunk,
)
from privilab.domain.research import CitationReference

ROOT = Path(__file__).parents[2]
MODEL_OUTPUTS = ROOT / "fixtures/model_outputs"


def fixture_output(name: str) -> str:
    return (MODEL_OUTPUTS / name).read_text(encoding="utf-8")


def model_request() -> ModelRequest:
    return ModelRequest(
        task_text="Summarize only the supplied synthetic chunks.",
        source_chunks=(
            ModelSourceChunk(
                "synthetic-source-001",
                "synthetic-chunk-001",
                "First caller-supplied synthetic source chunk.",
            ),
            ModelSourceChunk(
                "synthetic-source-002",
                "synthetic-chunk-002",
                "Second caller-supplied synthetic source chunk.",
            ),
        ),
    )


def test_happy_path_is_deterministic_and_cites_only_supplied_chunks() -> None:
    provider = FixtureModelProvider(fixture_output("synthetic_happy_path_v1.json"))
    request = model_request()

    first = provider.generate(request)
    second = provider.generate(request)
    supplied_references = {
        (chunk.source_id, chunk.chunk_id) for chunk in request.source_chunks
    }

    assert first == second
    assert first.to_json() == second.to_json()
    assert first.citations == (
        CitationReference("synthetic-source-001", "synthetic-chunk-001"),
        CitationReference("synthetic-source-002", "synthetic-chunk-002"),
    )
    assert {
        (citation.source_id, citation.chunk_id) for citation in first.citations
    } <= supplied_references


def test_generation_does_not_depend_on_working_directory_or_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_json = fixture_output("synthetic_happy_path_v1.json")
    provider = FixtureModelProvider(output_json)
    request = model_request()
    expected = provider.generate(request)

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert provider.generate(request) == expected


def test_citation_failure_is_deterministic_visible_and_not_repaired() -> None:
    provider = FixtureModelProvider(
        fixture_output("synthetic_citation_failure_v1.json")
    )
    request = model_request()
    supplied_references = {
        (chunk.source_id, chunk.chunk_id) for chunk in request.source_chunks
    }

    first = provider.generate(request)
    second = provider.generate(request)
    citation = first.citations[0]

    assert first == second
    assert (citation.source_id, citation.chunk_id) not in supplied_references
    assert citation == CitationReference(
        "synthetic-source-not-supplied",
        "synthetic-chunk-not-supplied",
    )


def test_malformed_output_has_a_stable_explicit_failure() -> None:
    provider = FixtureModelProvider(
        fixture_output("synthetic_malformed_output_v1.json")
    )

    messages: list[str] = []
    causes: list[str] = []
    for _ in range(2):
        with pytest.raises(MalformedModelOutputError) as error:
            provider.generate(model_request())
        messages.append(str(error.value))
        assert error.value.__cause__ is not None
        causes.append(str(error.value.__cause__))

    assert messages == [
        "model output does not satisfy the research-result contract",
        "model output does not satisfy the research-result contract",
    ]
    assert causes == [
        "citation fields do not match the contract",
        "citation fields do not match the contract",
    ]


def test_model_request_and_source_chunks_are_minimal_immutable_values() -> None:
    request = model_request()

    assert set(ModelRequest.__dataclass_fields__) == {"task_text", "source_chunks"}
    assert set(ModelSourceChunk.__dataclass_fields__) == {
        "source_id",
        "chunk_id",
        "text",
    }
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.task_text = "Replacement"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.source_chunks[0].text = "Replacement"  # type: ignore[misc]


def test_model_request_rejects_duplicate_source_chunk_references() -> None:
    chunk = ModelSourceChunk(
        "synthetic-source-001",
        "synthetic-chunk-001",
        "Synthetic caller-supplied source chunk.",
    )

    with pytest.raises(ValueError, match="source chunk references must be unique"):
        ModelRequest("Synthetic task.", (chunk, chunk))


def test_fixture_provider_rejects_values_outside_its_typed_boundary() -> None:
    provider = FixtureModelProvider(fixture_output("synthetic_happy_path_v1.json"))

    with pytest.raises(TypeError, match="request must be a ModelRequest"):
        provider.generate("Synthetic task")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="output_json must be a string"):
        FixtureModelProvider({})  # type: ignore[arg-type]
