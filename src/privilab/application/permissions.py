"""Deterministic synthetic permission-policy parsing and evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, cast

from privilab.domain import (
    ConditionId,
    PermissionResult,
    PermissionState,
    SyntheticRequestContext,
)

SUPPORTED_POLICY_SCHEMA_VERSION = 1


class PermissionPolicyParseError(ValueError):
    """Raised when a structured synthetic policy payload is invalid."""


class PermissionRuleEffect(StrEnum):
    """The deliberately narrow set of effects policy rules may express."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


class PermissionContextField(StrEnum):
    """The complete selector vocabulary supported by the P0 policy schema."""

    USER_ID = "user_id"
    ROLE_ID = "role_id"
    CLIENT_ID = "client_id"
    MATTER_ID = "matter_id"
    WORKFLOW_ID = "workflow_id"


def _validate_identifier(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty, trimmed string")


@dataclass(frozen=True, slots=True)
class PermissionSelector:
    """One exact-match selector in a parsed permission rule."""

    field: PermissionContextField
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.field, PermissionContextField):
            raise TypeError("selector field must be a PermissionContextField")
        _validate_identifier(self.value, "selector value")


@dataclass(frozen=True, slots=True)
class PermissionRule:
    """An immutable synthetic allow or block rule."""

    rule_id: str
    effect: PermissionRuleEffect
    selectors: tuple[PermissionSelector, ...] = ()
    condition_ids: frozenset[ConditionId] = frozenset()

    def __post_init__(self) -> None:
        _validate_identifier(self.rule_id, "rule_id")
        if not isinstance(self.effect, PermissionRuleEffect):
            raise TypeError("effect must be a PermissionRuleEffect")
        if not isinstance(self.selectors, tuple) or any(
            not isinstance(selector, PermissionSelector) for selector in self.selectors
        ):
            raise TypeError("selectors must be a tuple of PermissionSelector values")
        selector_fields = [selector.field for selector in self.selectors]
        if len(selector_fields) != len(set(selector_fields)):
            raise ValueError("a rule may select each context field at most once")
        if not isinstance(self.condition_ids, frozenset) or any(
            not isinstance(condition_id, ConditionId)
            for condition_id in self.condition_ids
        ):
            raise TypeError("condition_ids must be a frozenset of ConditionId values")
        if self.effect is PermissionRuleEffect.BLOCK and self.condition_ids:
            raise ValueError("BLOCK rules cannot contain condition IDs")


@dataclass(frozen=True, slots=True)
class PermissionPolicy:
    """A validated, immutable, synthetic P0 permission policy."""

    schema_version: int
    policy_id: str
    policy_version: str
    required_context: tuple[PermissionContextField, ...]
    rules: tuple[PermissionRule, ...]
    synthetic: Literal[True] = field(default=True, init=False)

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int:
            raise TypeError("schema_version must be an integer")
        if self.schema_version != SUPPORTED_POLICY_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported permission policy schema version: {self.schema_version}"
            )
        _validate_identifier(self.policy_id, "policy_id")
        _validate_identifier(self.policy_version, "policy_version")
        if not isinstance(self.required_context, tuple) or any(
            not isinstance(context_field, PermissionContextField)
            for context_field in self.required_context
        ):
            raise TypeError(
                "required_context must be a tuple of PermissionContextField values"
            )
        if len(self.required_context) != len(set(self.required_context)):
            raise ValueError("required_context must not contain duplicates")
        if not isinstance(self.rules, tuple) or any(
            not isinstance(rule, PermissionRule) for rule in self.rules
        ):
            raise TypeError("rules must be a tuple of PermissionRule values")
        rule_ids = [rule.rule_id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("rule IDs must be unique")

    @property
    def material_context(self) -> tuple[PermissionContextField, ...]:
        """Return every explicitly required or selector-used context field."""
        fields = set(self.required_context)
        fields.update(
            selector.field for rule in self.rules for selector in rule.selectors
        )
        return tuple(sorted(fields, key=lambda context_field: context_field.value))


_POLICY_FIELDS = frozenset(
    {
        "schema_version",
        "policy_id",
        "policy_version",
        "synthetic",
        "required_context",
        "rules",
    }
)
_RULE_FIELDS = frozenset({"rule_id", "effect", "match", "condition_ids"})


def _expect_mapping(value: object, field_name: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise PermissionPolicyParseError(f"{field_name} must be a mapping")
    return cast(Mapping[object, object], value)


def _expect_exact_fields(
    value: Mapping[object, object],
    expected_fields: frozenset[str],
    field_name: str,
) -> None:
    if set(value) != expected_fields:
        raise PermissionPolicyParseError(
            f"{field_name} fields must be exactly {sorted(expected_fields)}"
        )


def _expect_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise PermissionPolicyParseError(f"{field_name} must be a list")
    return cast(list[object], value)


def _parse_identifier(value: object, field_name: str) -> str:
    try:
        _validate_identifier(value, field_name)
    except (TypeError, ValueError) as error:
        raise PermissionPolicyParseError(str(error)) from error
    return cast(str, value)


def _parse_context_fields(value: object) -> tuple[PermissionContextField, ...]:
    raw_fields = _expect_list(value, "required_context")
    parsed_fields: list[PermissionContextField] = []
    for raw_field in raw_fields:
        field_name = _parse_identifier(raw_field, "required_context entry")
        try:
            parsed_fields.append(PermissionContextField(field_name))
        except ValueError as error:
            raise PermissionPolicyParseError(
                f"unsupported required context field: {field_name}"
            ) from error
    if len(parsed_fields) != len(set(parsed_fields)):
        raise PermissionPolicyParseError("required_context must not contain duplicates")
    return tuple(sorted(parsed_fields, key=lambda context_field: context_field.value))


def _parse_selectors(value: object, rule_id: str) -> tuple[PermissionSelector, ...]:
    raw_selectors = _expect_mapping(value, f"rule {rule_id} match")
    selectors: list[PermissionSelector] = []
    for raw_field, raw_value in raw_selectors.items():
        field_name = _parse_identifier(raw_field, f"rule {rule_id} selector name")
        try:
            context_field = PermissionContextField(field_name)
        except ValueError as error:
            raise PermissionPolicyParseError(
                f"unsupported selector: {field_name}"
            ) from error
        selector_value = _parse_identifier(
            raw_value, f"rule {rule_id} selector {field_name}"
        )
        selectors.append(PermissionSelector(context_field, selector_value))
    return tuple(sorted(selectors, key=lambda selector: selector.field.value))


def _parse_condition_ids(value: object, rule_id: str) -> frozenset[ConditionId]:
    raw_condition_ids = _expect_list(value, f"rule {rule_id} condition_ids")
    condition_values = [
        _parse_identifier(raw_value, f"rule {rule_id} condition ID")
        for raw_value in raw_condition_ids
    ]
    if len(condition_values) != len(set(condition_values)):
        raise PermissionPolicyParseError(
            f"rule {rule_id} condition_ids must not contain duplicates"
        )
    return frozenset(ConditionId(value) for value in condition_values)


def _parse_rule(value: object) -> PermissionRule:
    raw_rule = _expect_mapping(value, "rule")
    _expect_exact_fields(raw_rule, _RULE_FIELDS, "rule")
    rule_id = _parse_identifier(raw_rule["rule_id"], "rule_id")

    raw_effect = _parse_identifier(raw_rule["effect"], f"rule {rule_id} effect")
    try:
        effect = PermissionRuleEffect(raw_effect)
    except ValueError as error:
        raise PermissionPolicyParseError(
            f"unsupported rule effect: {raw_effect}"
        ) from error

    selectors = _parse_selectors(raw_rule["match"], rule_id)
    condition_ids = _parse_condition_ids(raw_rule["condition_ids"], rule_id)
    if effect is PermissionRuleEffect.BLOCK and condition_ids:
        raise PermissionPolicyParseError(
            f"BLOCK rule {rule_id} cannot contain condition IDs"
        )
    return PermissionRule(rule_id, effect, selectors, condition_ids)


def parse_permission_policy(payload: Mapping[str, object]) -> PermissionPolicy:
    """Strictly parse an already-loaded schema-version-1 synthetic policy."""
    raw_policy = _expect_mapping(payload, "permission policy")
    _expect_exact_fields(raw_policy, _POLICY_FIELDS, "permission policy")

    schema_version = raw_policy["schema_version"]
    if type(schema_version) is not int:
        raise PermissionPolicyParseError("schema_version must be an integer")
    if schema_version != SUPPORTED_POLICY_SCHEMA_VERSION:
        raise PermissionPolicyParseError(
            f"unsupported permission policy schema version: {schema_version}"
        )
    if raw_policy["synthetic"] is not True:
        raise PermissionPolicyParseError("synthetic must be exactly true")

    policy_id = _parse_identifier(raw_policy["policy_id"], "policy_id")
    policy_version = _parse_identifier(raw_policy["policy_version"], "policy_version")
    required_context = _parse_context_fields(raw_policy["required_context"])
    raw_rules = _expect_list(raw_policy["rules"], "rules")
    rules = [_parse_rule(raw_rule) for raw_rule in raw_rules]
    rule_ids = [rule.rule_id for rule in rules]
    if len(rule_ids) != len(set(rule_ids)):
        raise PermissionPolicyParseError("rule IDs must be unique")

    return PermissionPolicy(
        schema_version=schema_version,
        policy_id=policy_id,
        policy_version=policy_version,
        required_context=required_context,
        rules=tuple(sorted(rules, key=lambda rule: rule.rule_id)),
    )


def _context_values(
    context: SyntheticRequestContext,
) -> dict[PermissionContextField, str | None]:
    user = context.user
    return {
        PermissionContextField.USER_ID: (
            None if user is None or user.identity is None else user.identity.user_id
        ),
        PermissionContextField.ROLE_ID: (
            None if user is None or user.role is None else user.role.role_id
        ),
        PermissionContextField.CLIENT_ID: (
            None if context.client is None else context.client.client_id
        ),
        PermissionContextField.MATTER_ID: (
            None if context.matter is None else context.matter.matter_id
        ),
        PermissionContextField.WORKFLOW_ID: (
            None if context.workflow is None else context.workflow.workflow_id
        ),
    }


def _rule_applies(
    rule: PermissionRule,
    context_values: Mapping[PermissionContextField, str | None],
) -> bool:
    return all(
        context_values[selector.field] == selector.value for selector in rule.selectors
    )


def evaluate_permission(
    policy: PermissionPolicy,
    context: SyntheticRequestContext,
    *,
    satisfied_conditions: frozenset[ConditionId] = frozenset(),
) -> PermissionResult:
    """Evaluate one context with precedence BLOCK > UNKNOWN > CONDITIONAL > ALLOW."""
    if not isinstance(policy, PermissionPolicy):
        raise TypeError("policy must be a PermissionPolicy")
    if not isinstance(context, SyntheticRequestContext):
        raise TypeError("context must be a SyntheticRequestContext")
    if not isinstance(satisfied_conditions, frozenset) or any(
        not isinstance(condition_id, ConditionId)
        for condition_id in satisfied_conditions
    ):
        raise TypeError(
            "satisfied_conditions must be a frozenset of ConditionId values"
        )

    context_values = _context_values(context)

    # A conclusively applicable prohibition wins even when other material context
    # is unavailable. A selector with an unavailable value cannot match here.
    if any(
        rule.effect is PermissionRuleEffect.BLOCK
        and _rule_applies(rule, context_values)
        for rule in policy.rules
    ):
        return PermissionResult(PermissionState.BLOCK)

    if any(context_values[field] is None for field in policy.material_context):
        return PermissionResult(PermissionState.UNKNOWN)

    applicable_allows = tuple(
        rule
        for rule in policy.rules
        if rule.effect is PermissionRuleEffect.ALLOW
        and _rule_applies(rule, context_values)
    )
    if not applicable_allows:
        return PermissionResult(PermissionState.UNKNOWN)

    required_conditions = frozenset(
        condition_id
        for rule in applicable_allows
        for condition_id in rule.condition_ids
    )
    unresolved_conditions = required_conditions - satisfied_conditions
    if unresolved_conditions:
        return PermissionResult(
            PermissionState.CONDITIONAL,
            unresolved_conditions,
        )
    return PermissionResult(PermissionState.ALLOW)


def permits_protected_progression(permission_result: PermissionResult) -> bool:
    """Fail closed unless the supplied permission result is an effective ALLOW."""
    return (
        isinstance(permission_result, PermissionResult)
        and permission_result.state is PermissionState.ALLOW
        and not permission_result.condition_ids
    )


__all__ = [
    "PermissionContextField",
    "PermissionPolicy",
    "PermissionPolicyParseError",
    "PermissionRule",
    "PermissionRuleEffect",
    "PermissionSelector",
    "SUPPORTED_POLICY_SCHEMA_VERSION",
    "evaluate_permission",
    "parse_permission_policy",
    "permits_protected_progression",
]
