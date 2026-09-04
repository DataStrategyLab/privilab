from __future__ import annotations

import dataclasses
import json

import pytest

from privilab.domain.permissions import ConditionId, PermissionResult, PermissionState


@pytest.mark.parametrize(
    "state",
    [
        PermissionState.ALLOW,
        PermissionState.CONDITIONAL,
        PermissionState.BLOCK,
        PermissionState.UNKNOWN,
    ],
)
def test_approved_permission_states_are_accepted_and_serialize_exactly(
    state: PermissionState,
) -> None:
    result = PermissionResult(state)

    assert PermissionState(state.value) is state
    assert json.loads(result.to_json()) == {"condition_ids": [], "state": state.name}
    assert PermissionResult.from_json(result.to_json()) == result


def test_permission_state_namespace_contains_only_approved_names() -> None:
    assert set(PermissionState.__members__) == {
        "ALLOW",
        "CONDITIONAL",
        "BLOCK",
        "UNKNOWN",
    }
    serialized_schema = PermissionResult(PermissionState.UNKNOWN).to_json()
    for unrelated_name in ("G1", "G2", "G3"):
        assert unrelated_name not in PermissionState.__members__
        assert unrelated_name not in serialized_schema


def test_unapproved_permission_state_is_rejected_on_construction_and_parsing() -> None:
    with pytest.raises(ValueError):
        PermissionState("DENY")
    with pytest.raises(TypeError, match="state must be a PermissionState"):
        PermissionResult("ALLOW")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unsupported permission state: DENY"):
        PermissionResult.from_json('{"condition_ids":[],"state":"DENY"}')


@pytest.mark.parametrize(
    "condition_ids",
    [
        frozenset(),
        frozenset({ConditionId("condition-synthetic-001")}),
        frozenset(
            {
                ConditionId("condition-synthetic-001"),
                ConditionId("condition-synthetic-002"),
            }
        ),
    ],
)
def test_condition_ids_round_trip_without_evaluation(
    condition_ids: frozenset[ConditionId],
) -> None:
    result = PermissionResult(PermissionState.CONDITIONAL, condition_ids)

    assert PermissionResult.from_json(result.to_json()) == result


def test_condition_id_order_does_not_change_canonical_json() -> None:
    first = PermissionResult(
        PermissionState.CONDITIONAL,
        frozenset({ConditionId("condition-b"), ConditionId("condition-a")}),
    )
    second = PermissionResult(
        PermissionState.CONDITIONAL,
        frozenset({ConditionId("condition-a"), ConditionId("condition-b")}),
    )

    assert first == second
    assert first.to_json() == second.to_json()
    assert json.loads(first.to_json())["condition_ids"] == [
        "condition-a",
        "condition-b",
    ]


def test_permission_result_is_immutable() -> None:
    result = PermissionResult(
        PermissionState.UNKNOWN,
        frozenset({ConditionId("condition-synthetic-001")}),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.state = PermissionState.ALLOW  # type: ignore[misc]
    with pytest.raises(AttributeError):
        result.condition_ids.add(ConditionId("condition-synthetic-002"))  # type: ignore[attr-defined]
