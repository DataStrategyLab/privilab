"""Immutable authorization-scoped retrieval contracts."""

from __future__ import annotations

from dataclasses import dataclass


def _validate_identifier(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty, trimmed string")


def _validate_text(value: object, field_name: str) -> None:
    _validate_identifier(value, field_name)


@dataclass(frozen=True, slots=True, order=True)
class SourceId:
    """Stable application-controlled source identifier."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(self.value, "source ID")


@dataclass(frozen=True, slots=True, order=True)
class ChunkId:
    """Stable application-controlled chunk identifier."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(self.value, "chunk ID")


@dataclass(frozen=True, slots=True)
class AccessScope:
    """An application-authorized, exact-match retrieval capability.

    Instances are intentionally created only by the application-layer permission
    gate.  The constructor is not a supported public path for minting scopes.
    """

    user_id: str
    role_id: str
    client_id: str
    matter_id: str
    workflow_id: str

    def __init__(
        self,
        user_id: str,
        role_id: str,
        client_id: str,
        matter_id: str,
        workflow_id: str,
        *,
        _authorized: object | None = None,
    ) -> None:
        if _authorized is not _ACCESS_SCOPE_AUTHORITY:
            raise TypeError("AccessScope instances must be created by access_scope_for")
        for field_name, value in (
            ("user_id", user_id),
            ("role_id", role_id),
            ("client_id", client_id),
            ("matter_id", matter_id),
            ("workflow_id", workflow_id),
        ):
            _validate_identifier(value, field_name)
            object.__setattr__(self, field_name, value)


_ACCESS_SCOPE_AUTHORITY = object()


def _authorized_access_scope(
    *,
    user_id: str,
    role_id: str,
    client_id: str,
    matter_id: str,
    workflow_id: str,
) -> AccessScope:
    """Create a scope after the application permission gate has approved it."""
    return AccessScope(
        user_id,
        role_id,
        client_id,
        matter_id,
        workflow_id,
        _authorized=_ACCESS_SCOPE_AUTHORITY,
    )


@dataclass(frozen=True, slots=True)
class SourceEntitlement:
    """One trusted, exact source entitlement; no wildcard semantics exist."""

    source_id: SourceId
    user_id: str
    role_id: str
    client_id: str
    matter_id: str
    workflow_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, SourceId):
            raise TypeError("source_id must be a SourceId")
        for field_name in (
            "user_id",
            "role_id",
            "client_id",
            "matter_id",
            "workflow_id",
        ):
            _validate_identifier(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class RetrievalChunk:
    """A stable, trusted chunk supplied for local indexing."""

    chunk_id: ChunkId
    source_id: SourceId
    ordinal: int
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.chunk_id, ChunkId):
            raise TypeError("chunk_id must be a ChunkId")
        if not isinstance(self.source_id, SourceId):
            raise TypeError("source_id must be a SourceId")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer")
        _validate_text(self.text, "chunk text")


@dataclass(frozen=True, slots=True)
class RetrievalSource:
    """A source, its caller-supplied stable chunks, and trusted entitlements."""

    source_id: SourceId
    title: str
    chunks: tuple[RetrievalChunk, ...]
    entitlements: tuple[SourceEntitlement, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, SourceId):
            raise TypeError("source_id must be a SourceId")
        _validate_text(self.title, "source title")
        if not isinstance(self.chunks, tuple) or any(
            not isinstance(chunk, RetrievalChunk) for chunk in self.chunks
        ):
            raise TypeError("chunks must be a tuple of RetrievalChunk values")
        if any(chunk.source_id != self.source_id for chunk in self.chunks):
            raise ValueError("every chunk must belong to the source")
        if len({chunk.chunk_id for chunk in self.chunks}) != len(self.chunks):
            raise ValueError("chunk IDs must be unique within a source")
        if len({chunk.ordinal for chunk in self.chunks}) != len(self.chunks):
            raise ValueError("chunk ordinals must be unique within a source")
        if not isinstance(self.entitlements, tuple) or any(
            not isinstance(entitlement, SourceEntitlement)
            for entitlement in self.entitlements
        ):
            raise TypeError("entitlements must be a tuple of SourceEntitlement values")
        if any(
            entitlement.source_id != self.source_id for entitlement in self.entitlements
        ):
            raise ValueError("every entitlement must belong to the source")
        if len(set(self.entitlements)) != len(self.entitlements):
            raise ValueError("source entitlements must be unique")


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """An immutable, already-authorized retrieval result."""

    source_id: SourceId
    chunk_id: ChunkId
    ordinal: int
    title: str
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, SourceId):
            raise TypeError("source_id must be a SourceId")
        if not isinstance(self.chunk_id, ChunkId):
            raise TypeError("chunk_id must be a ChunkId")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer")
        _validate_text(self.title, "source title")
        _validate_text(self.text, "chunk text")


__all__ = [
    "AccessScope",
    "ChunkId",
    "RetrievedChunk",
    "RetrievalChunk",
    "RetrievalSource",
    "SourceEntitlement",
    "SourceId",
]
