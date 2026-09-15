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


@dataclass(frozen=True, slots=True, init=False)
class GovernedFixtureBinding:
    """One verified governed fixture artifact and its execution provider."""

    provider: ModelProvider
    model_id: str
    model_version: str
    content_hash: str
    provider_id: str
    provider_version: str

    def __init__(
        self,
        *,
        provider: ModelProvider,
        model_id: str,
        model_version: str,
        content_hash: str,
        provider_id: str,
        provider_version: str,
        _authorized: object | None = None,
    ) -> None:
        if _authorized is not _GOVERNED_FIXTURE_BINDING_AUTHORITY:
            raise TypeError(
                "GovernedFixtureBinding must be created by load_governed_fixture"
            )
        if not callable(getattr(provider, "generate", None)):
            raise TypeError("provider must implement ModelProvider")
        for field_name, value in (
            ("model_id", model_id),
            ("model_version", model_version),
            ("provider_id", provider_id),
            ("provider_version", provider_version),
        ):
            _validate_identifier(value, field_name)
        if (
            not isinstance(content_hash, str)
            or len(content_hash) != 71
            or not content_hash.startswith("sha256:")
            or any(
                character not in "0123456789abcdef" for character in content_hash[7:]
            )
        ):
            raise ValueError("content_hash must be a sha256-prefixed digest")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_version", model_version)
        object.__setattr__(self, "content_hash", content_hash)
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "provider_version", provider_version)


_GOVERNED_FIXTURE_BINDING_AUTHORITY = object()


def _authorized_governed_fixture_binding(
    *,
    provider: ModelProvider,
    model_id: str,
    model_version: str,
    content_hash: str,
    provider_id: str,
    provider_version: str,
) -> GovernedFixtureBinding:
    """Bind metadata only after an adapter verifies the governed fixture bytes."""
    return GovernedFixtureBinding(
        provider=provider,
        model_id=model_id,
        model_version=model_version,
        content_hash=content_hash,
        provider_id=provider_id,
        provider_version=provider_version,
        _authorized=_GOVERNED_FIXTURE_BINDING_AUTHORITY,
    )


__all__ = [
    "GovernedFixtureBinding",
    "MalformedModelOutputError",
    "ModelProvider",
    "ModelRequest",
    "ModelSourceChunk",
]
