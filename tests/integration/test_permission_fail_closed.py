from __future__ import annotations

from privilab.application.permissions import (
    evaluate_permission,
    parse_permission_policy,
    permits_protected_progression,
)
from privilab.domain import (
    ClientContext,
    ConditionId,
    MatterContext,
    PermissionState,
    Role,
    SyntheticRequestContext,
    UserContext,
    UserIdentity,
    WorkflowContext,
)


def test_inline_synthetic_policy_controls_progression_without_retrieval() -> None:
    policy = parse_permission_policy(
        {
            "schema_version": 1,
            "policy_id": "synthetic-policy-integration",
            "policy_version": "1.0.0",
            "synthetic": True,
            "required_context": [
                "user_id",
                "role_id",
                "client_id",
                "matter_id",
                "workflow_id",
            ],
            "rules": [
                {
                    "rule_id": "block-synthetic-user",
                    "effect": "BLOCK",
                    "match": {"user_id": "synthetic-user-blocked"},
                    "condition_ids": [],
                },
                {
                    "rule_id": "allow-synthetic-workflow",
                    "effect": "ALLOW",
                    "match": {
                        "role_id": "synthetic-researcher",
                        "workflow_id": "synthetic-workflow-001",
                    },
                    "condition_ids": ["condition-synthetic-review"],
                },
            ],
        }
    )
    authorized_context = SyntheticRequestContext(
        user=UserContext(
            UserIdentity("synthetic-user-001"),
            Role("synthetic-researcher"),
        ),
        client=ClientContext("synthetic-client-001"),
        matter=MatterContext("synthetic-matter-001"),
        workflow=WorkflowContext("synthetic-workflow-001"),
    )
    missing_context = SyntheticRequestContext(
        user=authorized_context.user,
        client=authorized_context.client,
        workflow=authorized_context.workflow,
    )
    blocked_context = SyntheticRequestContext(
        user=UserContext(
            UserIdentity("synthetic-user-blocked"),
            Role("synthetic-researcher"),
        )
    )

    unresolved = evaluate_permission(policy, authorized_context)
    resolved = evaluate_permission(
        policy,
        authorized_context,
        satisfied_conditions=frozenset({ConditionId("condition-synthetic-review")}),
    )
    unknown = evaluate_permission(policy, missing_context)
    blocked = evaluate_permission(policy, blocked_context)

    assert unresolved.state is PermissionState.CONDITIONAL
    assert resolved.state is PermissionState.ALLOW
    assert unknown.state is PermissionState.UNKNOWN
    assert blocked.state is PermissionState.BLOCK
    assert unresolved.state is PermissionState.CONDITIONAL
    assert permits_protected_progression(unresolved) is False
    assert permits_protected_progression(unknown) is False
    assert permits_protected_progression(blocked) is False
    assert permits_protected_progression(resolved) is True
