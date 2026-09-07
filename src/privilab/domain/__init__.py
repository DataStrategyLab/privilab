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

__all__ = [
    "CitationReference",
    "ClientContext",
    "ConditionId",
    "MatterContext",
    "PermissionResult",
    "PermissionState",
    "Role",
    "ResearchResult",
    "SyntheticRequestContext",
    "UserContext",
    "UserIdentity",
    "WorkflowContext",
]
