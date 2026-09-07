from __future__ import annotations

import json

import pytest

from privilab.domain.context import (
    ClientContext,
    MatterContext,
    Role,
    SyntheticRequestContext,
    UserContext,
    UserIdentity,
    WorkflowContext,
)


def test_synthetic_context_serializes_explicit_marker_and_nested_context() -> None:
    context = SyntheticRequestContext(
        user=UserContext(
            identity=UserIdentity("synthetic-user-001"),
            role=Role("synthetic-researcher"),
        ),
        client=ClientContext("synthetic-client-001"),
        matter=MatterContext("synthetic-matter-001"),
        workflow=WorkflowContext("synthetic-workflow-001"),
    )

    assert context.synthetic is True
    assert json.loads(context.to_json()) == {
        "client": {"client_id": "synthetic-client-001"},
        "matter": {"matter_id": "synthetic-matter-001"},
        "synthetic": True,
        "user": {
            "identity": {"user_id": "synthetic-user-001"},
            "role": {"role_id": "synthetic-researcher"},
        },
        "workflow": {"workflow_id": "synthetic-workflow-001"},
    }


def test_synthetic_context_cannot_describe_non_synthetic_context() -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument 'synthetic'"):
        SyntheticRequestContext(synthetic=False)  # type: ignore[call-arg]


def test_missing_context_is_representable_without_deciding_an_outcome() -> None:
    context = SyntheticRequestContext(user=UserContext())

    assert json.loads(context.to_json()) == {
        "client": None,
        "matter": None,
        "synthetic": True,
        "user": {"identity": None, "role": None},
        "workflow": None,
    }


def test_equivalent_contexts_have_identical_canonical_json() -> None:
    first = SyntheticRequestContext(
        user=UserContext(UserIdentity("synthetic-user-002"), Role("reviewer")),
        client=ClientContext("synthetic-client-002"),
        matter=MatterContext("synthetic-matter-002"),
        workflow=WorkflowContext("synthetic-workflow-002"),
    )
    second = SyntheticRequestContext(
        workflow=WorkflowContext("synthetic-workflow-002"),
        matter=MatterContext("synthetic-matter-002"),
        client=ClientContext("synthetic-client-002"),
        user=UserContext(UserIdentity("synthetic-user-002"), Role("reviewer")),
    )

    assert first == second
    assert first.to_json() == second.to_json()


def test_synthetic_context_parses_its_canonical_json() -> None:
    context = SyntheticRequestContext(
        user=UserContext(UserIdentity("synthetic-user-002"), Role("reviewer")),
        client=ClientContext("synthetic-client-002"),
        matter=MatterContext("synthetic-matter-002"),
        workflow=WorkflowContext("synthetic-workflow-002"),
    )

    assert SyntheticRequestContext.from_json(context.to_json()) == context


@pytest.mark.parametrize(
    "payload",
    [
        '{"client":null,"matter":null,"user":null,"workflow":null}',
        '{"client":{"client_id":false},"matter":null,"synthetic":true,"user":null,"workflow":null}',
        '{"client":null,"matter":null,"synthetic":false,"user":null,"workflow":null}',
    ],
)
def test_synthetic_context_rejects_payloads_outside_its_contract(payload: str) -> None:
    with pytest.raises(ValueError):
        SyntheticRequestContext.from_json(payload)


@pytest.mark.parametrize(
    ("payload", "field_name"),
    [
        (
            '{"client":null,"matter":null,"synthetic":false,"synthetic":true,'
            '"user":null,"workflow":null}',
            "synthetic",
        ),
        (
            '{"client":{"client_id":"first","client_id":"second"},'
            '"matter":null,"synthetic":true,"user":null,"workflow":null}',
            "client_id",
        ),
    ],
)
def test_synthetic_context_rejects_duplicate_fields(
    payload: str, field_name: str
) -> None:
    with pytest.raises(
        ValueError, match=f"duplicate request context field '{field_name}'"
    ):
        SyntheticRequestContext.from_json(payload)
