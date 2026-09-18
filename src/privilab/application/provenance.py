"""Application-owned, metadata-first provenance contracts and persistence port."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from privilab.application.permissions import PermissionPolicy
from privilab.domain import PermissionResult, PermissionState, SyntheticRequestContext

_CONFIGURATION_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _validate_identifier(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty, trimmed string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field_name} must be UTF-8 encodable") from error


def _validate_optional_identifier(value: object, field_name: str) -> None:
    if value is not None:
        _validate_identifier(value, field_name)


class RunStatus(StrEnum):
    """Terminal states required by the P0 orchestration slice."""

    PERMISSION_STOPPED = "PERMISSION_STOPPED"
    GENERATED = "GENERATED"
    FAILED = "FAILED"


class PermissionStopReason(StrEnum):
    """Application-authored explanations for fail-closed permission stops."""

    BLOCK = "BLOCK"
    UNKNOWN = "UNKNOWN"
    UNRESOLVED_CONDITIONS = "UNRESOLVED_CONDITIONS"


class FailureStage(StrEnum):
    """The protected stage at which orchestration safely failed."""

    PERMISSION = "PERMISSION"
    AUTHORIZATION = "AUTHORIZATION"
    RETRIEVAL = "RETRIEVAL"
    MODEL = "MODEL"


@dataclass(frozen=True, slots=True, order=True)
class RunId:
    """Immutable authoritative identity for one attempted run."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(self.value, "run ID")


@dataclass(frozen=True, slots=True)
class RunConfiguration:
    """Explicit, non-secret governed configuration used for one run."""

    configuration_id: str
    configuration_version: str
    provider_id: str
    provider_version: str
    model_id: str
    model_version: str
    retrieval_provider_id: str
    retrieval_provider_version: str
    retrieval_limit: int = 10
    options: tuple[tuple[str, str], ...] = ()
    model_content_hash: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "configuration_id",
            "configuration_version",
            "provider_id",
            "provider_version",
            "model_id",
            "model_version",
            "retrieval_provider_id",
            "retrieval_provider_version",
        ):
            _validate_identifier(getattr(self, field_name), field_name)
        if (
            type(self.retrieval_limit) is not int
            or not 1 <= self.retrieval_limit <= 100
        ):
            raise ValueError("retrieval_limit must be an integer from 1 to 100")
        if self.model_content_hash is not None and (
            not isinstance(self.model_content_hash, str)
            or not _CONFIGURATION_HASH.fullmatch(self.model_content_hash)
        ):
            raise ValueError(
                "model_content_hash must be None or a sha256-prefixed digest"
            )
        if not isinstance(self.options, tuple) or any(
            not isinstance(option, tuple)
            or len(option) != 2
            or not isinstance(option[0], str)
            or not isinstance(option[1], str)
            for option in self.options
        ):
            raise TypeError("options must be a tuple of string pairs")
        option_names = [name for name, _value in self.options]
        if len(option_names) != len(set(option_names)):
            raise ValueError("configuration option names must be unique")
        for name, value in self.options:
            _validate_identifier(name, "configuration option name")
            _validate_identifier(value, f"configuration option {name}")
        object.__setattr__(self, "options", tuple(sorted(self.options)))


def governed_configuration_hash(
    configuration: RunConfiguration,
    policy: PermissionPolicy,
) -> str:
    """Hash the explicit policy, retrieval, and model configuration canonically."""
    if not isinstance(configuration, RunConfiguration):
        raise TypeError("configuration must be a RunConfiguration")
    if not isinstance(policy, PermissionPolicy):
        raise TypeError("policy must be a PermissionPolicy")
    governed_values = {
        "configuration": {
            "configuration_id": configuration.configuration_id,
            "configuration_version": configuration.configuration_version,
            "options": dict(configuration.options),
        },
        "model": {
            "content_hash": configuration.model_content_hash,
            "model_id": configuration.model_id,
            "model_version": configuration.model_version,
            "provider_id": configuration.provider_id,
            "provider_version": configuration.provider_version,
        },
        "permission_policy": {
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "required_context": sorted(
                field.value for field in policy.required_context
            ),
            "rules": [
                {
                    "condition_ids": sorted(
                        condition_id.value for condition_id in rule.condition_ids
                    ),
                    "effect": rule.effect.value,
                    "match": {
                        selector.field.value: selector.value
                        for selector in sorted(
                            rule.selectors,
                            key=lambda item: item.field.value,
                        )
                    },
                    "rule_id": rule.rule_id,
                }
                for rule in sorted(policy.rules, key=lambda item: item.rule_id)
            ],
            "schema_version": policy.schema_version,
        },
        "retrieval": {
            "limit": configuration.retrieval_limit,
            "provider_id": configuration.retrieval_provider_id,
            "provider_version": configuration.retrieval_provider_version,
        },
    }
    canonical = json.dumps(
        governed_values,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


@dataclass(frozen=True, slots=True)
class ContextProvenance:
    """Synthetic context identifiers retained without request or prompt content."""

    user_id: str | None
    role_id: str | None
    client_id: str | None
    matter_id: str | None
    workflow_id: str | None
    synthetic: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "user_id",
            "role_id",
            "client_id",
            "matter_id",
            "workflow_id",
        ):
            _validate_optional_identifier(getattr(self, field_name), field_name)
        if self.synthetic is not True:
            raise ValueError("context provenance must remain synthetic")

    @classmethod
    def from_context(cls, context: SyntheticRequestContext) -> ContextProvenance:
        """Project the existing context contract to metadata-only provenance."""
        if not isinstance(context, SyntheticRequestContext):
            raise TypeError("context must be a SyntheticRequestContext")
        user = context.user
        return cls(
            user_id=(
                None if user is None or user.identity is None else user.identity.user_id
            ),
            role_id=None if user is None or user.role is None else user.role.role_id,
            client_id=None if context.client is None else context.client.client_id,
            matter_id=None if context.matter is None else context.matter.matter_id,
            workflow_id=(
                None if context.workflow is None else context.workflow.workflow_id
            ),
        )


@dataclass(frozen=True, slots=True)
class PermissionProvenance:
    """Trusted permission decision and its unresolved condition identifiers."""

    policy_id: str
    policy_version: str
    policy_schema_version: int
    state: PermissionState
    unresolved_condition_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_identifier(self.policy_id, "policy_id")
        _validate_identifier(self.policy_version, "policy_version")
        if type(self.policy_schema_version) is not int:
            raise TypeError("policy_schema_version must be an integer")
        if not isinstance(self.state, PermissionState):
            raise TypeError("state must be a PermissionState")
        if not isinstance(self.unresolved_condition_ids, tuple):
            raise TypeError("unresolved_condition_ids must be a tuple")
        if tuple(sorted(set(self.unresolved_condition_ids))) != (
            self.unresolved_condition_ids
        ):
            raise ValueError("unresolved_condition_ids must be unique and sorted")
        for condition_id in self.unresolved_condition_ids:
            _validate_identifier(condition_id, "unresolved condition ID")
        if self.state is not PermissionState.CONDITIONAL and (
            self.unresolved_condition_ids
        ):
            raise ValueError("only CONDITIONAL may have unresolved condition IDs")
        if (
            self.state is PermissionState.CONDITIONAL
            and not self.unresolved_condition_ids
        ):
            raise ValueError("CONDITIONAL requires unresolved condition IDs")

    @classmethod
    def from_result(
        cls,
        policy: PermissionPolicy,
        result: PermissionResult,
    ) -> PermissionProvenance:
        """Create policy-bound provenance from application evaluation output."""
        if not isinstance(policy, PermissionPolicy):
            raise TypeError("policy must be a PermissionPolicy")
        if not isinstance(result, PermissionResult):
            raise TypeError("result must be a PermissionResult")
        return cls(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            policy_schema_version=policy.schema_version,
            state=result.state,
            unresolved_condition_ids=tuple(
                sorted(condition_id.value for condition_id in result.condition_ids)
            ),
        )


@dataclass(frozen=True, slots=True)
class ChunkProvenance:
    """Metadata for an exact chunk returned by authorized retrieval."""

    chunk_id: str
    ordinal: int
    retrieval_position: int

    def __post_init__(self) -> None:
        _validate_identifier(self.chunk_id, "chunk_id")
        if type(self.ordinal) is not int or not 0 <= self.ordinal <= 2**63 - 1:
            raise ValueError("ordinal must fit a non-negative SQLite integer")
        if (
            type(self.retrieval_position) is not int
            or not 0 <= self.retrieval_position <= 2**63 - 1
        ):
            raise ValueError(
                "retrieval_position must fit a non-negative SQLite integer"
            )


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    """Governed source version and the exact authorized chunks used."""

    source_id: str
    source_version: str
    chunks: tuple[ChunkProvenance, ...]

    def __post_init__(self) -> None:
        _validate_identifier(self.source_id, "source_id")
        _validate_identifier(self.source_version, "source_version")
        if not isinstance(self.chunks, tuple) or any(
            not isinstance(chunk, ChunkProvenance) for chunk in self.chunks
        ):
            raise TypeError("chunks must be a tuple of ChunkProvenance values")
        if not self.chunks:
            raise ValueError("source provenance requires at least one chunk")
        chunk_ids = [chunk.chunk_id for chunk in self.chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("chunk IDs must be unique within a source")


@dataclass(frozen=True, slots=True)
class RunProvenance:
    """One complete append-only metadata record for a terminal run state."""

    run_id: RunId
    started_at: datetime
    completed_at: datetime
    status: RunStatus
    context: ContextProvenance
    configuration: RunConfiguration
    configuration_hash: str
    permission: PermissionProvenance | None
    retrieval_called: bool
    model_called: bool
    sources: tuple[SourceProvenance, ...] = ()
    stop_reason: PermissionStopReason | None = None
    failure_stage: FailureStage | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, RunId):
            raise TypeError("run_id must be a RunId")
        timestamps = (
            (self.started_at, "started_at"),
            (self.completed_at, "completed_at"),
        )
        for value, field_name in timestamps:
            if not isinstance(value, datetime) or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be a timezone-aware datetime")
        normalized = []
        for value, field_name in timestamps:
            try:
                normalized.append(value.astimezone(UTC))
            except OverflowError as error:
                raise ValueError(
                    f"{field_name} must be representable in UTC"
                ) from error
        started_at, completed_at = normalized
        if completed_at < started_at:
            raise ValueError("completed_at must not precede started_at")
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "completed_at", completed_at)
        if not isinstance(self.status, RunStatus):
            raise TypeError("status must be a RunStatus")
        if not isinstance(self.context, ContextProvenance):
            raise TypeError("context must be ContextProvenance")
        if not isinstance(self.configuration, RunConfiguration):
            raise TypeError("configuration must be a RunConfiguration")
        if not isinstance(self.configuration_hash, str) or not (
            _CONFIGURATION_HASH.fullmatch(self.configuration_hash)
        ):
            raise ValueError("configuration_hash must be a sha256-prefixed digest")
        if self.permission is not None and not isinstance(
            self.permission, PermissionProvenance
        ):
            raise TypeError("permission must be PermissionProvenance or None")
        if type(self.retrieval_called) is not bool:
            raise TypeError("retrieval_called must be a boolean")
        if type(self.model_called) is not bool:
            raise TypeError("model_called must be a boolean")
        if not isinstance(self.sources, tuple) or any(
            not isinstance(source, SourceProvenance) for source in self.sources
        ):
            raise TypeError("sources must be a tuple of SourceProvenance values")
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source IDs must be unique within a run")
        all_chunk_ids = [
            chunk.chunk_id for source in self.sources for chunk in source.chunks
        ]
        if len(all_chunk_ids) != len(set(all_chunk_ids)):
            raise ValueError("chunk IDs must be unique within a run")
        retrieval_positions = [
            chunk.retrieval_position
            for source in self.sources
            for chunk in source.chunks
        ]
        if sorted(retrieval_positions) != list(range(len(retrieval_positions))):
            raise ValueError(
                "retrieval positions must be unique and contiguous from zero"
            )
        if self.model_called and not self.retrieval_called:
            raise ValueError("model call requires a prior retrieval call")
        if self.sources and not self.retrieval_called:
            raise ValueError("source provenance requires a retrieval call")
        if self.retrieval_called and (
            self.permission is None
            or self.permission.state is not PermissionState.ALLOW
        ):
            raise ValueError("retrieval call requires an effective ALLOW decision")

        if self.status is RunStatus.PERMISSION_STOPPED:
            if self.permission is None or self.stop_reason is None:
                raise ValueError("permission-stopped runs require stop provenance")
            if (
                self.retrieval_called
                or self.model_called
                or self.sources
                or self.failure_stage is not None
            ):
                raise ValueError("permission-stopped runs cannot show later execution")
            expected_reason = {
                PermissionState.BLOCK: PermissionStopReason.BLOCK,
                PermissionState.UNKNOWN: PermissionStopReason.UNKNOWN,
                PermissionState.CONDITIONAL: (
                    PermissionStopReason.UNRESOLVED_CONDITIONS
                ),
            }.get(self.permission.state)
            if self.stop_reason is not expected_reason:
                raise ValueError("stop_reason must match the permission decision")
        elif self.status is RunStatus.GENERATED:
            if (
                self.permission is None
                or self.permission.state is not PermissionState.ALLOW
                or not self.retrieval_called
                or not self.model_called
                or self.stop_reason is not None
                or self.failure_stage is not None
            ):
                raise ValueError("generated run provenance is inconsistent")
        elif self.status is RunStatus.FAILED:
            if self.failure_stage is None or self.stop_reason is not None:
                raise ValueError("failed runs require only a failure stage")
            if self.failure_stage is FailureStage.PERMISSION:
                if self.permission is not None:
                    raise ValueError(
                        "permission failure cannot have a completed decision"
                    )
            elif (
                self.permission is None
                or self.permission.state is not PermissionState.ALLOW
            ):
                raise ValueError(
                    "post-permission failure requires an effective ALLOW decision"
                )
            expected_calls = {
                FailureStage.PERMISSION: (False, False),
                FailureStage.AUTHORIZATION: (False, False),
                FailureStage.RETRIEVAL: (True, False),
                FailureStage.MODEL: (True, True),
            }[self.failure_stage]
            if (self.retrieval_called, self.model_called) != expected_calls:
                raise ValueError("failure stage does not match provider call history")

    @property
    def chunks_in_retrieval_order(
        self,
    ) -> tuple[tuple[str, str, ChunkProvenance], ...]:
        """Return source identity and chunk metadata in exact model-context order."""
        chunks = (
            (source.source_id, source.source_version, chunk)
            for source in self.sources
            for chunk in source.chunks
        )
        return tuple(sorted(chunks, key=lambda item: item[2].retrieval_position))


class ProvenanceStore(Protocol):
    """Append-only application port for trusted run provenance."""

    def append(self, provenance: RunProvenance) -> None:
        """Append one immutable terminal record."""
        ...

    def get(self, run_id: RunId) -> RunProvenance | None:
        """Return one previously persisted run without changing it."""
        ...


__all__ = [
    "ChunkProvenance",
    "ContextProvenance",
    "FailureStage",
    "PermissionProvenance",
    "PermissionStopReason",
    "ProvenanceStore",
    "RunConfiguration",
    "RunId",
    "RunProvenance",
    "RunStatus",
    "SourceProvenance",
    "governed_configuration_hash",
]
