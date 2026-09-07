from __future__ import annotations

import dataclasses
from copy import deepcopy
from typing import cast

import pytest

from privilab.application.permissions import (
    PermissionContextField,
    PermissionPolicyParseError,
    PermissionRuleEffect,
    parse_permission_policy,
)


def valid_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "policy_id": "synthetic-policy-001",
        "policy_version": "1.0.0",
        "synthetic": True,
        "required_context": ["workflow_id", "user_id"],
        "rules": [
            {
                "rule_id": "allow-synthetic-research",
                "effect": "ALLOW",
                "match": {
                    "role_id": "synthetic-researcher",
                    "client_id": "synthetic-client-001",
                },
                "condition_ids": [
                    "condition-synthetic-training",
                    "condition-synthetic-review",
                ],
            },
            {
                "rule_id": "block-synthetic-user",
                "effect": "BLOCK",
                "match": {"user_id": "synthetic-user-blocked"},
                "condition_ids": [],
            },
        ],
    }


def test_valid_policy_is_strictly_typed_synthetic_and_deterministic() -> None:
    first_payload = valid_payload()
    second_payload = valid_payload()
    second_payload["required_context"] = ["user_id", "workflow_id"]
    second_payload["rules"] = list(
        reversed(cast(list[object], second_payload["rules"]))
    )
    first_rule = cast(dict[str, object], cast(list[object], second_payload["rules"])[1])
    first_rule["condition_ids"] = list(
        reversed(cast(list[object], first_rule["condition_ids"]))
    )
    first_rule["match"] = {
        "client_id": "synthetic-client-001",
        "role_id": "synthetic-researcher",
    }

    first = parse_permission_policy(first_payload)
    second = parse_permission_policy(second_payload)

    assert first == second
    assert first.schema_version == 1
    assert first.synthetic is True
    assert first.required_context == (
        PermissionContextField.USER_ID,
        PermissionContextField.WORKFLOW_ID,
    )
    assert first.material_context == (
        PermissionContextField.CLIENT_ID,
        PermissionContextField.ROLE_ID,
        PermissionContextField.USER_ID,
        PermissionContextField.WORKFLOW_ID,
    )
    assert first.rules[0].effect is PermissionRuleEffect.ALLOW
    assert isinstance(first.rules, tuple)
    assert isinstance(first.rules[0].selectors, tuple)
    assert isinstance(first.rules[0].condition_ids, frozenset)


def test_parsed_policy_structures_are_immutable() -> None:
    policy = parse_permission_policy(valid_payload())

    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.policy_id = "replacement"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.rules[0].effect = PermissionRuleEffect.BLOCK  # type: ignore[misc]
    with pytest.raises(AttributeError):
        policy.rules[0].condition_ids.add("replacement")  # type: ignore[attr-defined]


@pytest.mark.parametrize("schema_version", [0, 2, "1", True, None])
def test_unsupported_or_incorrect_schema_version_is_rejected(
    schema_version: object,
) -> None:
    payload = valid_payload()
    payload["schema_version"] = schema_version

    with pytest.raises(PermissionPolicyParseError):
        parse_permission_policy(payload)


@pytest.mark.parametrize("synthetic", [False, "true", 1, None])
def test_non_synthetic_or_coerced_marker_is_rejected(synthetic: object) -> None:
    payload = valid_payload()
    payload["synthetic"] = synthetic

    with pytest.raises(PermissionPolicyParseError, match="synthetic"):
        parse_permission_policy(payload)


def test_missing_synthetic_marker_is_rejected() -> None:
    payload = valid_payload()
    del payload["synthetic"]

    with pytest.raises(PermissionPolicyParseError, match="fields"):
        parse_permission_policy(payload)


@pytest.mark.parametrize("location", ["policy", "rule"])
def test_unknown_policy_and_rule_fields_are_rejected(location: str) -> None:
    payload = valid_payload()
    if location == "policy":
        payload["unexpected"] = True
    else:
        rule = cast(dict[str, object], cast(list[object], payload["rules"])[0])
        rule["unexpected"] = True

    with pytest.raises(PermissionPolicyParseError, match="fields"):
        parse_permission_policy(payload)


def test_unsupported_selector_is_rejected() -> None:
    payload = valid_payload()
    rule = cast(dict[str, object], cast(list[object], payload["rules"])[0])
    rule["match"] = {"jurisdiction": "synthetic-jurisdiction"}

    with pytest.raises(PermissionPolicyParseError, match="unsupported selector"):
        parse_permission_policy(payload)


@pytest.mark.parametrize("effect", ["UNKNOWN", "CONDITIONAL", "allow", 1, None])
def test_unsupported_or_incorrect_rule_effect_is_rejected(effect: object) -> None:
    payload = valid_payload()
    rule = cast(dict[str, object], cast(list[object], payload["rules"])[0])
    rule["effect"] = effect

    with pytest.raises(PermissionPolicyParseError):
        parse_permission_policy(payload)


@pytest.mark.parametrize(
    ("path", "bad_value"),
    [
        ("policy_id", ""),
        ("policy_id", " untrimmed"),
        ("policy_version", 1),
        ("rule_id", " "),
        ("selector_value", "synthetic-client-001 "),
        ("condition_id", None),
    ],
)
def test_malformed_identifiers_are_rejected(path: str, bad_value: object) -> None:
    payload = valid_payload()
    rule = cast(dict[str, object], cast(list[object], payload["rules"])[0])
    if path in {"policy_id", "policy_version"}:
        payload[path] = bad_value
    elif path == "rule_id":
        rule["rule_id"] = bad_value
    elif path == "selector_value":
        rule["match"] = {"client_id": bad_value}
    else:
        rule["condition_ids"] = [bad_value]

    with pytest.raises(PermissionPolicyParseError):
        parse_permission_policy(payload)


def test_duplicate_rule_ids_are_rejected() -> None:
    payload = valid_payload()
    rules = cast(list[object], payload["rules"])
    duplicate = deepcopy(cast(dict[str, object], rules[0]))
    rules.append(duplicate)

    with pytest.raises(PermissionPolicyParseError, match="rule IDs must be unique"):
        parse_permission_policy(payload)


def test_duplicate_condition_ids_are_rejected_before_collapsing() -> None:
    payload = valid_payload()
    rule = cast(dict[str, object], cast(list[object], payload["rules"])[0])
    rule["condition_ids"] = ["condition-duplicate", "condition-duplicate"]

    with pytest.raises(PermissionPolicyParseError, match="must not contain duplicates"):
        parse_permission_policy(payload)


def test_duplicate_required_context_is_rejected_before_collapsing() -> None:
    payload = valid_payload()
    payload["required_context"] = ["user_id", "user_id"]

    with pytest.raises(PermissionPolicyParseError, match="must not contain duplicates"):
        parse_permission_policy(payload)


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("required_context", ("user_id",)),
        ("rules", ()),
    ],
)
def test_sequence_types_are_not_silently_coerced(
    field_name: str, bad_value: object
) -> None:
    payload = valid_payload()
    payload[field_name] = bad_value

    with pytest.raises(PermissionPolicyParseError, match="must be a list"):
        parse_permission_policy(payload)


def test_block_rules_cannot_hide_ignored_conditions() -> None:
    payload = valid_payload()
    block_rule = cast(dict[str, object], cast(list[object], payload["rules"])[1])
    block_rule["condition_ids"] = ["condition-invalid-on-block"]

    with pytest.raises(PermissionPolicyParseError, match="BLOCK rule"):
        parse_permission_policy(payload)
