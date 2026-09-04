"""Immutable P0 permission-outcome contracts without policy behavior."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Self, cast


class PermissionState(StrEnum):
    """The complete application-controlled P0 permission-state vocabulary."""

    ALLOW = "ALLOW"
    CONDITIONAL = "CONDITIONAL"
    BLOCK = "BLOCK"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True, order=True)
class ConditionId:
    """Stable identifier for a condition; it carries no evaluation behavior."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("condition ID must be a string")
        if not self.value or self.value != self.value.strip():
            raise ValueError("condition ID must be a non-empty, trimmed string")


@dataclass(frozen=True, slots=True)
class PermissionResult:
    """A permission outcome and its explicit, immutable condition identifiers."""

    state: PermissionState
    condition_ids: frozenset[ConditionId] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.state, PermissionState):
            raise TypeError("state must be a PermissionState")
        if not isinstance(self.condition_ids, frozenset):
            raise TypeError("condition_ids must be a frozenset")
        if any(not isinstance(item, ConditionId) for item in self.condition_ids):
            raise TypeError("condition_ids must contain only ConditionId values")

    def to_json(self) -> str:
        """Return the canonical JSON representation of this result."""
        value = {
            "condition_ids": sorted(item.value for item in self.condition_ids),
            "state": self.state.value,
        }
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, payload: str) -> Self:
        """Parse a permission result without evaluating permission policy."""
        try:
            decoded: object = json.loads(payload)
        except (json.JSONDecodeError, TypeError) as error:
            raise ValueError("permission result must be valid JSON") from error
        if not isinstance(decoded, dict):
            raise ValueError("permission result JSON must be an object")
        value = cast(dict[str, object], decoded)
        if set(value) != {"condition_ids", "state"}:
            raise ValueError("permission result fields do not match the contract")

        state_value = value["state"]
        if not isinstance(state_value, str):
            raise ValueError("permission state must be a string")
        try:
            state = PermissionState(state_value)
        except ValueError as error:
            raise ValueError(f"unsupported permission state: {state_value}") from error

        condition_values = value["condition_ids"]
        if not isinstance(condition_values, list) or any(
            not isinstance(item, str) for item in condition_values
        ):
            raise ValueError("condition_ids must be an array of strings")
        condition_strings = cast(list[str], condition_values)
        if len(condition_strings) != len(set(condition_strings)):
            raise ValueError("condition_ids must not contain duplicates")
        try:
            condition_ids = frozenset(ConditionId(item) for item in condition_strings)
        except (TypeError, ValueError) as error:
            raise ValueError("condition_ids contains an invalid identifier") from error
        return cls(state=state, condition_ids=condition_ids)
