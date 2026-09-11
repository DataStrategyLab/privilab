from __future__ import annotations

import dataclasses
import json

import pytest

from privilab.domain.research import CitationReference, ResearchResult


def test_research_result_is_immutable_and_canonical() -> None:
    result = ResearchResult(
        answer_text="Synthetic answer.",
        citations=(
            CitationReference("synthetic-source-002", "synthetic-chunk-002"),
            CitationReference("synthetic-source-001", "synthetic-chunk-001"),
        ),
    )

    assert ResearchResult.from_json(result.to_json()) == result
    assert json.loads(result.to_json()) == {
        "answer_text": "Synthetic answer.",
        "citations": [
            {
                "chunk_id": "synthetic-chunk-002",
                "source_id": "synthetic-source-002",
            },
            {
                "chunk_id": "synthetic-chunk-001",
                "source_id": "synthetic-source-001",
            },
        ],
    }
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.answer_text = "Replacement"  # type: ignore[misc]


def test_citation_order_is_preserved_without_support_validation() -> None:
    result = ResearchResult.from_json(
        '{"answer_text":"Synthetic answer.","citations":['
        '{"source_id":"unsupported-source","chunk_id":"unsupported-chunk"},'
        '{"source_id":"synthetic-source-001","chunk_id":"synthetic-chunk-001"}'
        "]}"
    )

    assert result.citations == (
        CitationReference("unsupported-source", "unsupported-chunk"),
        CitationReference("synthetic-source-001", "synthetic-chunk-001"),
    )


@pytest.mark.parametrize(
    "payload",
    [
        "not JSON",
        "[]",
        '{"answer_text":"Synthetic answer."}',
        '{"answer_text":false,"citations":[]}',
        '{"answer_text":"Synthetic answer.","citations":{}}',
        '{"answer_text":"Synthetic answer.","citations":[false]}',
        (
            '{"answer_text":"Synthetic answer.","citations":'
            '[{"source_id":"synthetic-source-001"}]}'
        ),
        (
            '{"answer_text":"Synthetic answer.","citations":'
            '[{"source_id":"synthetic-source-001","chunk_id":false}]}'
        ),
    ],
)
def test_research_result_rejects_payloads_outside_the_schema(payload: str) -> None:
    with pytest.raises(ValueError):
        ResearchResult.from_json(payload)


def test_research_result_rejects_duplicate_json_fields() -> None:
    payload = '{"answer_text":"first","answer_text":"second","citations":[]}'

    with pytest.raises(
        ValueError, match="duplicate research result field 'answer_text'"
    ):
        ResearchResult.from_json(payload)


def test_excessively_nested_json_is_normalized_at_the_decoder_boundary() -> None:
    depth = 10_000
    payload = "[" * depth + "null" + "]" * depth

    with pytest.raises(RecursionError):
        json.loads(payload)

    with pytest.raises(
        ValueError, match="^research result must be valid JSON$"
    ) as error:
        ResearchResult.from_json(payload)

    assert type(error.value) is ValueError
    assert isinstance(error.value.__cause__, RecursionError)


@pytest.mark.parametrize("surrogate", [r"\ud800", r"\udfff"])
def test_escaped_lone_surrogate_in_answer_text_is_rejected(
    surrogate: str,
) -> None:
    payload = f'{{"answer_text":"Synthetic {surrogate} answer.","citations":[]}}'
    decoded = json.loads(payload)

    assert any(
        0xD800 <= ord(character) <= 0xDFFF for character in decoded["answer_text"]
    )
    with pytest.raises(ValueError, match="^research result contains an invalid value$"):
        ResearchResult.from_json(payload)


def test_direct_research_result_construction_rejects_surrogates() -> None:
    with pytest.raises(
        ValueError, match="^answer_text must contain only Unicode scalar values$"
    ):
        ResearchResult("Synthetic \ud800 answer.")


@pytest.mark.parametrize(
    ("source_id", "chunk_id", "field_name"),
    [
        ("synthetic-source-\ud800", "synthetic-chunk-001", "source_id"),
        ("synthetic-source-001", "synthetic-chunk-\udfff", "chunk_id"),
    ],
)
def test_direct_citation_construction_rejects_surrogates(
    source_id: str,
    chunk_id: str,
    field_name: str,
) -> None:
    with pytest.raises(
        ValueError,
        match=rf"^{field_name} must contain only Unicode scalar values$",
    ):
        CitationReference(source_id, chunk_id)


@pytest.mark.parametrize("field_name", ["source_id", "chunk_id"])
def test_escaped_surrogate_in_citation_identifier_is_rejected(
    field_name: str,
) -> None:
    citation = {
        "source_id": "synthetic-source-001",
        "chunk_id": "synthetic-chunk-001",
    }
    citation[field_name] += r"\ud800"
    payload = json.dumps(
        {"answer_text": "Synthetic answer.", "citations": [citation]}
    ).replace(r"\\ud800", r"\ud800")
    decoded = json.loads(payload)

    assert 0xD800 <= ord(decoded["citations"][0][field_name][-1]) <= 0xDFFF
    with pytest.raises(ValueError, match="^citation contains an invalid identifier$"):
        ResearchResult.from_json(payload)


def test_ordinary_non_ascii_unicode_remains_supported() -> None:
    result = ResearchResult(
        "Résumé of the synthetic 東京 source.",
        (CitationReference("source-café", "chunk-東京"),),
    )

    assert ResearchResult.from_json(result.to_json()) == result
    assert "Résumé" in result.to_json()
    assert "東京" in result.to_json()


def test_supplementary_unicode_round_trips_and_encodes_as_utf8() -> None:
    result = ResearchResult(
        "Synthetic answer 😀.",
        (CitationReference("source-😀", "chunk-🚀"),),
    )

    canonical_json = result.to_json()

    assert "😀" in canonical_json
    assert "🚀" in canonical_json
    assert ResearchResult.from_json(canonical_json) == result
    assert canonical_json.encode("utf-8").decode("utf-8") == canonical_json


@pytest.mark.parametrize(
    ("source_id", "chunk_id"),
    [
        ("", "synthetic-chunk-001"),
        (" synthetic-source-001", "synthetic-chunk-001"),
        ("synthetic-source-001", " "),
    ],
)
def test_citation_identifiers_must_be_non_empty_and_trimmed(
    source_id: str,
    chunk_id: str,
) -> None:
    with pytest.raises(ValueError):
        CitationReference(source_id, chunk_id)


def test_research_result_constructor_does_not_coerce_mutable_citations() -> None:
    with pytest.raises(TypeError, match="citations must be a tuple"):
        ResearchResult(
            "Synthetic answer.",
            [  # type: ignore[arg-type]
                CitationReference("synthetic-source-001", "synthetic-chunk-001")
            ],
        )
