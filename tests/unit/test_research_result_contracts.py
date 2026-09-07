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
