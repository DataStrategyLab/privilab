"""Typed domain contracts for the controlled PriviLAB reference demo."""

from privilab.domain.context import (
    ClientContext,
    MatterContext,
    Role,
    SyntheticRequestContext,
    UserContext,
    UserIdentity,
    WorkflowContext,
)
from privilab.domain.permissions import ConditionId, PermissionResult, PermissionState
from privilab.domain.research import CitationReference, ResearchResult
from privilab.domain.retrieval import (
    AccessScope,
    ChunkId,
    RetrievalChunk,
    RetrievalSource,
    RetrievedChunk,
    SourceEntitlement,
    SourceId,
)

__all__ = [
    "CitationReference",
    "ClientContext",
    "AccessScope",
    "ChunkId",
    "ConditionId",
    "MatterContext",
    "PermissionResult",
    "PermissionState",
    "ResearchResult",
    "Role",
    "RetrievedChunk",
    "RetrievalChunk",
    "RetrievalSource",
    "SourceEntitlement",
    "SourceId",
    "SyntheticRequestContext",
    "UserContext",
    "UserIdentity",
    "WorkflowContext",
]
