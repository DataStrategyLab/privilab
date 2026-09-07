"""Immutable provider-neutral research-result contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Self, cast


def _validate_identifier(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty, trimmed string")


def _validate_text(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must contain non-whitespace text")


def _object_without_duplicate_fields(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for field_name, field_value in pairs:
        if field_name in value:
            raise ValueError(f"duplicate research result field {field_name!r}")
        value[field_name] = field_value
    return value


@dataclass(frozen=True, slots=True)
class CitationReference:
    """Stable provider-neutral reference to one source chunk."""

    source_id: str
    chunk_id: str

    def __post_init__(self) -> None:
        _validate_identifier(self.source_id, "source_id")
        _validate_identifier(self.chunk_id, "chunk_id")


@dataclass(frozen=True, slots=True)
class ResearchResult:
    """Structured research text and its ordered citation references."""

    answer_text: str
    citations: tuple[CitationReference, ...] = ()

    def __post_init__(self) -> None:
        _validate_text(self.answer_text, "answer_text")
        if not isinstance(self.citations, tuple) or any(
            not isinstance(citation, CitationReference) for citation in self.citations
        ):
            raise TypeError("citations must be a tuple of CitationReference values")

    def to_json(self) -> str:
        """Return the canonical JSON representation of this result."""
        value = {
            "answer_text": self.answer_text,
            "citations": [
                {
                    "chunk_id": citation.chunk_id,
                    "source_id": citation.source_id,
                }
                for citation in self.citations
            ],
        }
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, payload: str) -> Self:
        """Strictly parse untrusted structured provider output."""
        try:
            decoded: object = json.loads(
                payload,
                object_pairs_hook=_object_without_duplicate_fields,
            )
        except (json.JSONDecodeError, TypeError) as error:
            raise ValueError("research result must be valid JSON") from error
        if not isinstance(decoded, dict):
            raise ValueError("research result JSON must be an object")
        value = cast(dict[str, object], decoded)
        if set(value) != {"answer_text", "citations"}:
            raise ValueError("research result fields do not match the contract")

        answer_text = value["answer_text"]
        if not isinstance(answer_text, str):
            raise ValueError("answer_text must be a string")

        raw_citations = value["citations"]
        if not isinstance(raw_citations, list):
            raise ValueError("citations must be an array")
        citation_values = cast(list[object], raw_citations)
        citations: list[CitationReference] = []
        for raw_citation in citation_values:
            if not isinstance(raw_citation, dict):
                raise ValueError("citations must contain only objects")
            citation = cast(dict[str, object], raw_citation)
            if set(citation) != {"source_id", "chunk_id"}:
                raise ValueError("citation fields do not match the contract")
            source_id = citation["source_id"]
            chunk_id = citation["chunk_id"]
            if not isinstance(source_id, str) or not isinstance(chunk_id, str):
                raise ValueError("citation identifiers must be strings")
            try:
                citations.append(CitationReference(source_id, chunk_id))
            except (TypeError, ValueError) as error:
                raise ValueError("citation contains an invalid identifier") from error

        try:
            return cls(answer_text=answer_text, citations=tuple(citations))
        except (TypeError, ValueError) as error:
            raise ValueError("research result contains an invalid value") from error


__all__ = ["CitationReference", "ResearchResult"]
