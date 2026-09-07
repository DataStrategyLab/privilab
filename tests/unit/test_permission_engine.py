from __future__ import annotations

from collections.abc import Sequence

import pytest

from privilab.application.permissions import (
    PermissionContextField,
    evaluate_permission,
    parse_permission_policy,
    permits_protected_progression,
)
from privilab.domain import (
    ClientContext,
    ConditionId,
    MatterContext,
    PermissionResult,
    PermissionState,
    Role,
    SyntheticRequestContext,
    UserContext,
    UserIdentity,
    WorkflowContext,
)


def policy_payload(
    rules: list[dict[str, object]],
    *,
    required_context: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "policy_id": "synthetic-policy-engine-tests",
        "policy_version": "1.0.0",
        "synthetic": True,
        "required_context": list(required_context),
        "rules": rules,
    }


def rule(
    rule_id: str,
    effect: str,
    *,
    match: dict[str, object] | None = None,
    condition_ids: Sequence[object] = (),
) -> dict[str, object]:
    return {
        "rule_id": rule_id,
        "effect": effect,
        "match": {} if match is None else match,
        "condition_ids": list(condition_ids),
    }


def full_context() -> SyntheticRequestContext:
    return SyntheticRequestContext(
        user=UserContext(
            identity=UserIdentity("synthetic-user-001"),
            role=Role("synthetic-researcher"),
        ),
        client=ClientContext("synthetic-client-001"),
        matter=MatterContext("synthetic-matter-001"),
        workflow=WorkflowContext("synthetic-workflow-001"),
    )


def context_missing(field: PermissionContextField) -> SyntheticRequestContext:
    complete = full_context()
    user = complete.user
    assert user is not None
    if field is PermissionContextField.USER_ID:
        return SyntheticRequestContext(
            user=UserContext(role=user.role),
            client=complete.client,
            matter=complete.matter,
            workflow=complete.workflow,
        )
    if field is PermissionContextField.ROLE_ID:
        return SyntheticRequestContext(
            user=UserContext(identity=user.identity),
            client=complete.client,
            matter=complete.matter,
            workflow=complete.workflow,
        )
    if field is PermissionContextField.CLIENT_ID:
        return SyntheticRequestContext(
            user=user,
            matter=complete.matter,
            workflow=complete.workflow,
        )
    if field is PermissionContextField.MATTER_ID:
        return SyntheticRequestContext(
            user=user,
            client=complete.client,
            workflow=complete.workflow,
        )
    return SyntheticRequestContext(
        user=user,
        client=complete.client,
        matter=complete.matter,
    )


def test_global_allow_without_conditions_returns_allow() -> None:
    policy = parse_permission_policy(policy_payload([rule("allow-global", "ALLOW")]))

    result = evaluate_permission(policy, full_context())

    assert result == PermissionResult(PermissionState.ALLOW)


def test_applicable_allow_with_unresolved_condition_returns_conditional() -> None:
    condition = ConditionId("condition-synthetic-review")
    policy = parse_permission_policy(
        policy_payload(
            [rule("allow-reviewed", "ALLOW", condition_ids=[condition.value])]
        )
    )

    result = evaluate_permission(policy, full_context())

    assert result == PermissionResult(
        PermissionState.CONDITIONAL, frozenset({condition})
    )


def test_applicable_block_returns_block() -> None:
    policy = parse_permission_policy(
        policy_payload(
            [
                rule(
                    "block-user",
                    "BLOCK",
                    match={"user_id": "synthetic-user-001"},
                )
            ]
        )
    )

    assert evaluate_permission(policy, full_context()).state is PermissionState.BLOCK


def test_no_matching_positive_authorization_returns_unknown() -> None:
    policy = parse_permission_policy(
        policy_payload(
            [
                rule(
                    "allow-other-matter",
                    "ALLOW",
                    match={"matter_id": "synthetic-matter-other"},
                )
            ]
        )
    )

    assert evaluate_permission(policy, full_context()).state is PermissionState.UNKNOWN


@pytest.mark.parametrize(
    "condition_ids",
    [[], ["condition-synthetic-review"]],
)
def test_applicable_block_takes_precedence_over_allow(
    condition_ids: list[str],
) -> None:
    policy = parse_permission_policy(
        policy_payload(
            [
                rule("allow-matching", "ALLOW", condition_ids=condition_ids),
                rule("block-matching", "BLOCK"),
            ]
        )
    )

    assert evaluate_permission(policy, full_context()) == PermissionResult(
        PermissionState.BLOCK
    )


@pytest.mark.parametrize("field", list(PermissionContextField))
def test_each_material_context_field_fails_closed_when_missing(
    field: PermissionContextField,
) -> None:
    policy = parse_permission_policy(
        policy_payload(
            [rule("allow-global", "ALLOW")],
            required_context=[field.value],
        )
    )

    assert evaluate_permission(policy, context_missing(field)) == PermissionResult(
        PermissionState.UNKNOWN
    )


def test_selector_used_context_is_material_without_explicit_requirement() -> None:
    policy = parse_permission_policy(
        policy_payload(
            [
                rule(
                    "allow-user",
                    "ALLOW",
                    match={"user_id": "synthetic-user-001"},
                )
            ]
        )
    )

    result = evaluate_permission(
        policy,
        context_missing(PermissionContextField.USER_ID),
    )

    assert result.state is PermissionState.UNKNOWN


def test_conclusive_global_block_wins_when_material_context_is_missing() -> None:
    policy = parse_permission_policy(
        policy_payload(
            [
                rule("allow-workflow", "ALLOW"),
                rule("block-global", "BLOCK"),
            ],
            required_context=["workflow_id"],
        )
    )

    result = evaluate_permission(
        policy,
        context_missing(PermissionContextField.WORKFLOW_ID),
    )

    assert result.state is PermissionState.BLOCK


def test_decidable_specific_block_wins_when_other_material_context_is_missing() -> None:
    policy = parse_permission_policy(
        policy_payload(
            [
                rule(
                    "block-user",
                    "BLOCK",
                    match={"user_id": "synthetic-user-001"},
                ),
                rule("allow-matter", "ALLOW"),
            ],
            required_context=["matter_id"],
        )
    )

    result = evaluate_permission(
        policy,
        context_missing(PermissionContextField.MATTER_ID),
    )

    assert result.state is PermissionState.BLOCK


def test_missing_block_selector_cannot_be_treated_as_an_applicable_prohibition() -> (
    None
):
    policy = parse_permission_policy(
        policy_payload(
            [
                rule(
                    "block-user",
                    "BLOCK",
                    match={"user_id": "synthetic-user-001"},
                ),
                rule("allow-global", "ALLOW"),
            ]
        )
    )

    result = evaluate_permission(
        policy,
        context_missing(PermissionContextField.USER_ID),
    )

    assert result.state is PermissionState.UNKNOWN


@pytest.mark.parametrize(
    ("satisfied", "expected_state", "expected_unresolved"),
    [
        (frozenset(), PermissionState.CONDITIONAL, {"condition-a", "condition-b"}),
        (
            frozenset({ConditionId("condition-a")}),
            PermissionState.CONDITIONAL,
            {"condition-b"},
        ),
        (
            frozenset({ConditionId("condition-a"), ConditionId("condition-b")}),
            PermissionState.ALLOW,
            set(),
        ),
    ],
)
def test_multiple_conditions_are_collected_and_resolved_deterministically(
    satisfied: frozenset[ConditionId],
    expected_state: PermissionState,
    expected_unresolved: set[str],
) -> None:
    policy = parse_permission_policy(
        policy_payload(
            [
                rule("allow-b", "ALLOW", condition_ids=["condition-b"]),
                rule(
                    "allow-a-and-b",
                    "ALLOW",
                    condition_ids=["condition-b", "condition-a"],
                ),
            ]
        )
    )

    result = evaluate_permission(
        policy,
        full_context(),
        satisfied_conditions=satisfied,
    )

    assert result.state is expected_state
    assert {
        condition.value for condition in result.condition_ids
    } == expected_unresolved
    assert (
        result.to_json()
        == PermissionResult(
            expected_state,
            frozenset(ConditionId(value) for value in expected_unresolved),
        ).to_json()
    )


def test_rule_and_condition_input_order_cannot_change_the_result() -> None:
    first_rules = [
        rule("allow-b", "ALLOW", condition_ids=["condition-b"]),
        rule("allow-a", "ALLOW", condition_ids=["condition-a"]),
    ]
    second_rules = [
        rule("allow-a", "ALLOW", condition_ids=["condition-a"]),
        rule("allow-b", "ALLOW", condition_ids=["condition-b"]),
    ]

    first = evaluate_permission(
        parse_permission_policy(policy_payload(first_rules)), full_context()
    )
    second = evaluate_permission(
        parse_permission_policy(policy_payload(second_rules)), full_context()
    )

    assert first == second
    assert first.to_json() == second.to_json()


def test_later_condition_satisfaction_returns_new_result_without_mutation() -> None:
    condition = ConditionId("condition-synthetic-review")
    policy = parse_permission_policy(
        policy_payload(
            [rule("allow-reviewed", "ALLOW", condition_ids=[condition.value])]
        )
    )

    earlier = evaluate_permission(policy, full_context())
    later = evaluate_permission(
        policy,
        full_context(),
        satisfied_conditions=frozenset({condition}),
    )

    assert earlier is not later
    assert earlier == PermissionResult(
        PermissionState.CONDITIONAL, frozenset({condition})
    )
    assert later == PermissionResult(PermissionState.ALLOW)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (PermissionState.ALLOW, True),
        (PermissionState.CONDITIONAL, False),
        (PermissionState.BLOCK, False),
        (PermissionState.UNKNOWN, False),
    ],
)
def test_only_allow_permits_protected_progression(
    state: PermissionState,
    expected: bool,
) -> None:
    assert permits_protected_progression(PermissionResult(state)) is expected


@pytest.mark.parametrize(
    "result",
    [
        PermissionResult(
            PermissionState.ALLOW,
            frozenset({ConditionId("condition-unresolved")}),
        ),
        PermissionResult.from_json(
            '{"condition_ids":["condition-unresolved"],"state":"ALLOW"}'
        ),
    ],
)
def test_allow_with_conditions_cannot_cross_protected_progression_gate(
    result: PermissionResult,
) -> None:
    assert permits_protected_progression(result) is False


def test_gate_fails_closed_for_an_invalid_runtime_value() -> None:
    assert permits_protected_progression("ALLOW") is False  # type: ignore[arg-type]
