"""Application authorization gate and provider contract for retrieval."""

from __future__ import annotations

from typing import Protocol

from privilab.application.permissions import (
    PermissionPolicy,
    evaluate_permission,
    permits_protected_progression,
)
from privilab.domain import ConditionId, SyntheticRequestContext
from privilab.domain.retrieval import (
    AccessScope,
    RetrievedChunk,
    _authorized_access_scope,
)


def access_scope_for(
    context: SyntheticRequestContext,
    policy: PermissionPolicy,
    *,
    satisfied_conditions: frozenset[ConditionId] = frozenset(),
) -> AccessScope | None:
    """Evaluate this context and mint a scope only for effective ALLOW."""
    if not isinstance(context, SyntheticRequestContext):
        raise TypeError("context must be a SyntheticRequestContext")
    if not isinstance(policy, PermissionPolicy):
        raise TypeError("policy must be a PermissionPolicy")
    if not isinstance(satisfied_conditions, frozenset) or any(
        not isinstance(condition_id, ConditionId)
        for condition_id in satisfied_conditions
    ):
        raise TypeError(
            "satisfied_conditions must be a frozenset of ConditionId values"
        )
    permission_result = evaluate_permission(
        policy,
        context,
        satisfied_conditions=satisfied_conditions,
    )
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
