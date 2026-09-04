"""Immutable synthetic request-context contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal


def _validate_identifier(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty, trimmed string")


def _validate_optional_type(
    value: object,
    expected_type: type[object],
    field_name: str,
) -> None:
    if value is not None and not isinstance(value, expected_type):
        raise TypeError(f"{field_name} must be {expected_type.__name__} or None")


@dataclass(frozen=True, slots=True)
class UserIdentity:
    """Application-controlled identifier for a request user."""

    user_id: str

    def __post_init__(self) -> None:
        _validate_identifier(self.user_id, "user_id")


@dataclass(frozen=True, slots=True)
class Role:
    """Stable role identifier supplied as request context."""

    role_id: str

    def __post_init__(self) -> None:
        _validate_identifier(self.role_id, "role_id")


@dataclass(frozen=True, slots=True)
class UserContext:
    """User identity and role context, either of which may be unavailable."""

    identity: UserIdentity | None = None
    role: Role | None = None

    def __post_init__(self) -> None:
        _validate_optional_type(self.identity, UserIdentity, "identity")
        _validate_optional_type(self.role, Role, "role")


@dataclass(frozen=True, slots=True)
class ClientContext:
    """Stable client identifier supplied as request context."""

    client_id: str

    def __post_init__(self) -> None:
        _validate_identifier(self.client_id, "client_id")


@dataclass(frozen=True, slots=True)
class MatterContext:
    """Stable matter identifier supplied as request context."""

    matter_id: str

    def __post_init__(self) -> None:
        _validate_identifier(self.matter_id, "matter_id")


@dataclass(frozen=True, slots=True)
class WorkflowContext:
    """Stable workflow identifier supplied as request context."""

    workflow_id: str

    def __post_init__(self) -> None:
        _validate_identifier(self.workflow_id, "workflow_id")


@dataclass(frozen=True, slots=True)
class SyntheticRequestContext:
    """P0 request context whose synthetic boundary is explicit and fixed."""

    user: UserContext | None = None
    client: ClientContext | None = None
    matter: MatterContext | None = None
    workflow: WorkflowContext | None = None
    synthetic: Literal[True] = field(default=True, init=False)

    def __post_init__(self) -> None:
        _validate_optional_type(self.user, UserContext, "user")
        _validate_optional_type(self.client, ClientContext, "client")
        _validate_optional_type(self.matter, MatterContext, "matter")
        _validate_optional_type(self.workflow, WorkflowContext, "workflow")

    def to_json(self) -> str:
        """Return the canonical JSON representation of this context."""
        user: dict[str, object] | None = None
        if self.user is not None:
            identity = self.user.identity
            role = self.user.role
            user = {
                "identity": None if identity is None else {"user_id": identity.user_id},
                "role": None if role is None else {"role_id": role.role_id},
            }

        value: dict[str, object] = {
            "client": (
                None if self.client is None else {"client_id": self.client.client_id}
            ),
            "matter": (
                None if self.matter is None else {"matter_id": self.matter.matter_id}
            ),
            "synthetic": self.synthetic,
            "user": user,
            "workflow": (
                None
                if self.workflow is None
                else {"workflow_id": self.workflow.workflow_id}
            ),
        }
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
