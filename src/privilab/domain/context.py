"""Immutable synthetic request-context contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal, Self, cast


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


def _object_without_duplicate_fields(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for field_name, field_value in pairs:
        if field_name in value:
            raise ValueError(f"duplicate request context field {field_name!r}")
        value[field_name] = field_value
    return value


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

    @classmethod
    def from_json(cls, payload: str) -> Self:
        """Parse a synthetic request context without deriving any values."""
        try:
            decoded: object = json.loads(
                payload,
                object_pairs_hook=_object_without_duplicate_fields,
            )
        except (json.JSONDecodeError, TypeError) as error:
            raise ValueError("request context must be valid JSON") from error
        if not isinstance(decoded, dict):
            raise ValueError("request context JSON must be an object")
        value = cast(dict[str, object], decoded)
        if set(value) != {"client", "matter", "synthetic", "user", "workflow"}:
            raise ValueError("request context fields do not match the contract")
        if value["synthetic"] is not True:
            raise ValueError("request context must be synthetic")

        def optional_identifier(
            raw_value: object, field_name: str, identifier_name: str
        ) -> str | None:
            if raw_value is None:
                return None
            if not isinstance(raw_value, dict) or set(raw_value) != {identifier_name}:
                raise ValueError(f"{field_name} fields do not match the contract")
            identifier = raw_value[identifier_name]
            if not isinstance(identifier, str):
                raise ValueError(f"{field_name} identifier must be a string")
            return identifier

        client_id = optional_identifier(value["client"], "client", "client_id")
        matter_id = optional_identifier(value["matter"], "matter", "matter_id")
        workflow_id = optional_identifier(value["workflow"], "workflow", "workflow_id")

        raw_user = value["user"]
        if raw_user is None:
            user = None
        else:
            if not isinstance(raw_user, dict) or set(raw_user) != {"identity", "role"}:
                raise ValueError("user fields do not match the contract")
            user_id = optional_identifier(
                raw_user["identity"], "user identity", "user_id"
            )
            role_id = optional_identifier(raw_user["role"], "user role", "role_id")
            user = UserContext(
                identity=None if user_id is None else UserIdentity(user_id),
                role=None if role_id is None else Role(role_id),
            )

        return cls(
            user=user,
            client=None if client_id is None else ClientContext(client_id),
            matter=None if matter_id is None else MatterContext(matter_id),
            workflow=None if workflow_id is None else WorkflowContext(workflow_id),
        )
