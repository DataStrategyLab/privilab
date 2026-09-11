"""Application-owned model-provider port and its minimal request boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from privilab.domain.research import ResearchResult


def _validate_unicode_scalars(value: str, field_name: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValueError(f"{field_name} must contain only Unicode scalar values")


def _validate_identifier(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty, trimmed string")
    _validate_unicode_scalars(value, field_name)


def _validate_text(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must contain non-whitespace text")
    _validate_unicode_scalars(value, field_name)


class MalformedModelOutputError(ValueError):
    """Raised when provider output cannot satisfy the research-result contract."""


@dataclass(frozen=True, slots=True)
class ModelSourceChunk:
    """Source text supplied to a model after caller-controlled authorization."""

    source_id: str
    chunk_id: str
    text: str

    def __post_init__(self) -> None:
        _validate_identifier(self.source_id, "source_id")
        _validate_identifier(self.chunk_id, "chunk_id")
        _validate_text(self.text, "text")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """Minimal task and caller-supplied source chunks for model execution."""

    task_text: str
    source_chunks: tuple[ModelSourceChunk, ...]

    def __post_init__(self) -> None:
        _validate_text(self.task_text, "task_text")
        if not isinstance(self.source_chunks, tuple) or any(
            not isinstance(chunk, ModelSourceChunk) for chunk in self.source_chunks
        ):
            raise TypeError("source_chunks must be a tuple of ModelSourceChunk values")
        chunk_references = [
            (chunk.source_id, chunk.chunk_id) for chunk in self.source_chunks
        ]
        if len(chunk_references) != len(set(chunk_references)):
            raise ValueError("source chunk references must be unique")


class ModelProvider(Protocol):
    """Provider port whose caller must supply only already-authorized chunks."""

    def generate(self, request: ModelRequest) -> ResearchResult:
        """Generate one structured result from caller-supplied input."""
        ...


__all__ = [
    "MalformedModelOutputError",
    "ModelProvider",
    "ModelRequest",
    "ModelSourceChunk",
]
