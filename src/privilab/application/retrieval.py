"""Application authorization gate and provider contract for retrieval."""

from __future__ import annotations

from typing import Protocol

from privilab.application.permissions import permits_protected_progression
from privilab.domain import PermissionResult, SyntheticRequestContext
from privilab.domain.retrieval import (
    AccessScope,
    RetrievedChunk,
    _authorized_access_scope,
)


def access_scope_for(
    context: SyntheticRequestContext,
    permission_result: PermissionResult,
) -> AccessScope | None:
    """Mint an exact retrieval scope only for effective permission ALLOW."""
    if not isinstance(context, SyntheticRequestContext):
        raise TypeError("context must be a SyntheticRequestContext")
    if not isinstance(permission_result, PermissionResult):
        raise TypeError("permission_result must be a PermissionResult")
    if not permits_protected_progression(permission_result):
        return None

    user = context.user
    if (
        user is None
        or user.identity is None
        or user.role is None
        or context.client is None
        or context.matter is None
        or context.workflow is None
    ):
        return None
    return _authorized_access_scope(
        user_id=user.identity.user_id,
        role_id=user.role.role_id,
        client_id=context.client.client_id,
        matter_id=context.matter.matter_id,
        workflow_id=context.workflow.workflow_id,
    )


class RetrievalProvider(Protocol):
    """Narrow retrieval boundary that requires an authorized access scope."""

    def retrieve(
        self,
        query: str,
        access_scope: AccessScope,
        *,
        limit: int = 10,
    ) -> tuple[RetrievedChunk, ...]: ...


__all__ = ["RetrievalProvider", "access_scope_for"]
