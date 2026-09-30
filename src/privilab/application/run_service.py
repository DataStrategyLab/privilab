"""Application-owned orchestration for the approved P0 run sequence."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from privilab.application.model_provider import (
    ModelProvider,
    ModelRequest,
    ModelSourceChunk,
    _validate_text,
)
from privilab.application.permissions import (
    PermissionPolicy,
    evaluate_permission,
    permits_protected_progression,
)
from privilab.application.provenance import (
    ChunkProvenance,
    ContextProvenance,
    FailureStage,
    PermissionProvenance,
    PermissionStopReason,
    ProvenanceStore,
    RunConfiguration,
    RunId,
    RunProvenance,
    RunStatus,
    SourceProvenance,
    governed_configuration_hash,
)
from privilab.application.retrieval import RetrievalProvider, access_scope_for
from privilab.application.telemetry import (
    ModelUsage,
    PricingInput,
    build_telemetry,
    nonnegative_integer,
)
from privilab.domain import (
    ConditionId,
    PermissionResult,
    PermissionState,
    ResearchResult,
    RetrievedChunk,
    SyntheticRequestContext,
)

if TYPE_CHECKING:
    from privilab.adapters.models.openai import OpenAIProviderConfig


def _new_run_id() -> RunId:
    return RunId(str(uuid4()))


def _utc_now() -> datetime:
    return datetime.now(UTC)


_RUN_SERVICE_CONSTRUCTION_AUTHORITY = object()
_MISSING_PRICING = PricingInput()


@dataclass(frozen=True, slots=True)
class _ModelExecution:
    """Private, invocation-local handoff inside application orchestration."""

    result: ResearchResult | None
    usage: ModelUsage | None
    latency_ns: int


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """Structured application result without persisted prompt or source text."""

    run_id: RunId
    status: RunStatus
    permission_result: PermissionResult | None
    result: ResearchResult | None = None
    failure_stage: FailureStage | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, RunId):
            raise TypeError("run_id must be a RunId")
        if not isinstance(self.status, RunStatus):
            raise TypeError("status must be a RunStatus")
        if self.permission_result is not None and not isinstance(
            self.permission_result, PermissionResult
        ):
            raise TypeError("permission_result must be PermissionResult or None")
        if self.result is not None and not isinstance(self.result, ResearchResult):
            raise TypeError("result must be ResearchResult or None")
        if self.status is RunStatus.GENERATED:
            if self.result is None or self.failure_stage is not None:
                raise ValueError("generated outcomes require only a result")
        elif self.status is RunStatus.FAILED:
            if self.result is not None or self.failure_stage is None:
                raise ValueError("failed outcomes require only a failure stage")
        elif self.result is not None or self.failure_stage is not None:
            raise ValueError("permission-stopped outcomes cannot contain later results")


def _source_provenance(
    retrieved_chunks: tuple[RetrievedChunk, ...],
) -> tuple[SourceProvenance, ...]:
    if any(not isinstance(chunk, RetrievedChunk) for chunk in retrieved_chunks):
        raise TypeError("retrieval must return only RetrievedChunk values")
    source_order: list[str] = []
    source_versions: dict[str, str] = {}
    source_chunks: dict[str, list[ChunkProvenance]] = {}
    chunk_ids: set[str] = set()
    for retrieval_position, chunk in enumerate(retrieved_chunks):
        source_id = chunk.source_id.value
        chunk_id = chunk.chunk_id.value
        if chunk_id in chunk_ids:
            raise ValueError("retrieval returned a duplicate chunk ID")
        chunk_ids.add(chunk_id)
        if source_id not in source_chunks:
            source_order.append(source_id)
            source_versions[source_id] = chunk.source_version
            source_chunks[source_id] = []
        elif source_versions[source_id] != chunk.source_version:
            raise ValueError("one source ID cannot have multiple versions in a run")
        source_chunks[source_id].append(
            ChunkProvenance(
                chunk_id=chunk_id,
                ordinal=chunk.ordinal,
                retrieval_position=retrieval_position,
            )
        )
    return tuple(
        SourceProvenance(
            source_id=source_id,
            source_version=source_versions[source_id],
            chunks=tuple(source_chunks[source_id]),
        )
        for source_id in source_order
    )


def _stop_reason(result: PermissionResult) -> PermissionStopReason:
    if result.state is PermissionState.BLOCK:
        return PermissionStopReason.BLOCK
    if result.state is PermissionState.UNKNOWN:
        return PermissionStopReason.UNKNOWN
    if result.state is PermissionState.CONDITIONAL and result.condition_ids:
        return PermissionStopReason.UNRESOLVED_CONDITIONS
    raise ValueError("only fail-closed permission results have a stop reason")


class RunService:
    """Own permission → scoped retrieval → model → provenance progression."""

    def __init__(
        self,
        *,
        policy: PermissionPolicy,
        retrieval_provider: RetrievalProvider,
        model_provider: ModelProvider,
        provenance_store: ProvenanceStore,
        configuration: RunConfiguration,
        run_id_factory: Callable[[], RunId] = _new_run_id,
        clock: Callable[[], datetime] = _utc_now,
        _authorized: object | None = None,
        _execute_model: Callable[[ModelRequest], _ModelExecution] | None = None,
        _pricing: PricingInput = _MISSING_PRICING,
    ) -> None:
        if _authorized is not _RUN_SERVICE_CONSTRUCTION_AUTHORITY:
            raise TypeError(
                "RunService must be created by from_governed_fixture or an "
                "approved internal composition path"
            )
        if not isinstance(policy, PermissionPolicy):
            raise TypeError("policy must be a PermissionPolicy")
        if not isinstance(configuration, RunConfiguration):
            raise TypeError("configuration must be a RunConfiguration")
        if not callable(run_id_factory):
            raise TypeError("run_id_factory must be callable")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._policy = policy
        self._retrieval_provider = retrieval_provider
        self._model_provider = model_provider
        self._provenance_store = provenance_store
        self._configuration = configuration
        self._configuration_hash = governed_configuration_hash(
            configuration,
            policy,
        )
        self._run_id_factory = run_id_factory
        self._clock = clock
        self._execute_model = _execute_model
        self._pricing = _pricing

    @classmethod
    def from_governed_fixture(
        cls,
        *,
        policy: PermissionPolicy,
        retrieval_provider: RetrievalProvider,
        fixture_id: str,
        provenance_store: ProvenanceStore,
        configuration_id: str,
        configuration_version: str,
        retrieval_provider_id: str,
        retrieval_provider_version: str,
        retrieval_limit: int = 10,
        options: tuple[tuple[str, str], ...] = (),
        run_id_factory: Callable[[], RunId] = _new_run_id,
        clock: Callable[[], datetime] = _utc_now,
    ) -> RunService:
        """Compose a run service from the canonical governed fixture manifest."""
        from privilab.adapters.models.governed_fixture import load_governed_fixture

        governed_fixture = load_governed_fixture(fixture_id)
        configuration = RunConfiguration(
            configuration_id=configuration_id,
            configuration_version=configuration_version,
            provider_id=governed_fixture.provider_id,
            provider_version=governed_fixture.provider_version,
            model_id=governed_fixture.model_id,
            model_version=governed_fixture.model_version,
            retrieval_provider_id=retrieval_provider_id,
            retrieval_provider_version=retrieval_provider_version,
            retrieval_limit=retrieval_limit,
            options=options,
            model_content_hash=governed_fixture.content_hash,
        )
        return cls(
            policy=policy,
            retrieval_provider=retrieval_provider,
            model_provider=governed_fixture.provider,
            provenance_store=provenance_store,
            configuration=configuration,
            run_id_factory=run_id_factory,
            clock=clock,
            _authorized=_RUN_SERVICE_CONSTRUCTION_AUTHORITY,
        )

    @classmethod
    def from_openai(
        cls,
        *,
        policy: PermissionPolicy,
        retrieval_provider: RetrievalProvider,
        provenance_store: ProvenanceStore,
        configuration_id: str,
        configuration_version: str,
        retrieval_provider_id: str,
        retrieval_provider_version: str,
        provider_config: OpenAIProviderConfig | None = None,
        retrieval_limit: int = 10,
        run_id_factory: Callable[[], RunId] = _new_run_id,
        clock: Callable[[], datetime] = _utc_now,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        pricing: PricingInput = _MISSING_PRICING,
        live_case_id: str | None = None,
        live_case_version: str | None = None,
    ) -> RunService:
        """Compose the approved OpenAI path without credentials or model execution."""
        from privilab.adapters.models.openai import OpenAIProvider, OpenAIProviderConfig

        settings = (
            OpenAIProviderConfig() if provider_config is None else provider_config
        )
        provider = OpenAIProvider(settings)
        if not isinstance(pricing, PricingInput):
            raise TypeError("pricing must be an immutable PricingInput")
        if not callable(monotonic_ns):
            raise TypeError("monotonic_ns must be callable")
        if (live_case_id is None) != (live_case_version is None):
            raise ValueError("live case identity and version must be supplied together")
        case_options: tuple[tuple[str, str], ...] = ()
        # RunConfiguration validates all identity strings below.
        if live_case_id is not None:
            assert live_case_version is not None
            case_options = (
                ("live_case_id", live_case_id),
                ("live_case_version", live_case_version),
            )

        def execute(request: ModelRequest) -> _ModelExecution:
            generation = None
            begin = monotonic_ns()
            try:
                generation = provider.generate_with_usage(request)
            except Exception:
                pass  # Existing MODEL failure semantics; retain no exception.
            finally:
                end = monotonic_ns()
            nonnegative_integer(begin)
            nonnegative_integer(end)
            elapsed = end - begin
            nonnegative_integer(elapsed)
            if generation is None:
                return _ModelExecution(None, None, elapsed)
            reported = generation.usage
            try:
                usage = (
                    None
                    if reported is None
                    else ModelUsage(
                        input_tokens=reported.input_tokens,
                        output_tokens=reported.output_tokens,
                        total_tokens=reported.total_tokens,
                        cached_input_tokens=reported.cached_input_tokens,
                        cache_write_tokens=reported.cache_write_tokens,
                        reasoning_tokens=reported.reasoning_tokens,
                    )
                )
            except (TypeError, ValueError):
                # Invalid/unpersistable usage fails the model stage, retaining
                # the measured call interval without coercing any count.
                return _ModelExecution(None, None, elapsed)
            return _ModelExecution(generation.result, usage, elapsed)

        configuration = RunConfiguration(
            configuration_id=configuration_id,
            configuration_version=configuration_version,
            provider_id="openai-provider",
            provider_version="1",
            model_id=settings.model,
            model_version="alias:gpt-5.6-terra",
            retrieval_provider_id=retrieval_provider_id,
            retrieval_provider_version=retrieval_provider_version,
            retrieval_limit=retrieval_limit,
            options=settings.configuration_options()
            + pricing.configuration_options()
            + case_options,
        )
        return cls(
            policy=policy,
            retrieval_provider=retrieval_provider,
            model_provider=provider,
            provenance_store=provenance_store,
            configuration=configuration,
            run_id_factory=run_id_factory,
            clock=clock,
            _authorized=_RUN_SERVICE_CONSTRUCTION_AUTHORITY,
            _execute_model=execute,
            _pricing=pricing,
        )

    @classmethod
    def _from_components_for_testing(
        cls,
        *,
        policy: PermissionPolicy,
        retrieval_provider: RetrievalProvider,
        model_provider: ModelProvider,
        provenance_store: ProvenanceStore,
        configuration: RunConfiguration,
        run_id_factory: Callable[[], RunId] = _new_run_id,
        clock: Callable[[], datetime] = _utc_now,
    ) -> RunService:
        """Construct an ungoverned service only for isolated boundary tests."""
        if configuration.model_content_hash is not None:
            raise ValueError("governed model content requires from_governed_fixture")
        return cls(
            policy=policy,
            retrieval_provider=retrieval_provider,
            model_provider=model_provider,
            provenance_store=provenance_store,
            configuration=configuration,
            run_id_factory=run_id_factory,
            clock=clock,
            _authorized=_RUN_SERVICE_CONSTRUCTION_AUTHORITY,
        )

    def run(
        self,
        *,
        context: SyntheticRequestContext,
        task_text: str,
        query: str,
        satisfied_conditions: frozenset[ConditionId] = frozenset(),
    ) -> RunOutcome:
        """Execute one immutable attempt and append its trusted provenance."""
        _validate_text(task_text, "task_text")
        run_id = self._run_id_factory()
        if not isinstance(run_id, RunId):
            raise TypeError("run_id_factory must return a RunId")
        started_at = self._clock()
        context_provenance = ContextProvenance.from_context(context)

        try:
            permission_result = evaluate_permission(
                self._policy,
                context,
                satisfied_conditions=satisfied_conditions,
            )
        except Exception:
            return self._failed(
                run_id=run_id,
                started_at=started_at,
                context=context_provenance,
                permission_result=None,
                failure_stage=FailureStage.PERMISSION,
                retrieval_called=False,
                model_called=False,
            )

        if not permits_protected_progression(permission_result):
            permission = PermissionProvenance.from_result(
                self._policy,
                permission_result,
            )
            provenance = self._provenance(
                run_id=run_id,
                started_at=started_at,
                completed_at=self._clock(),
                status=RunStatus.PERMISSION_STOPPED,
                context=context_provenance,
                permission=permission,
                retrieval_called=False,
                model_called=False,
                stop_reason=_stop_reason(permission_result),
            )
            self._provenance_store.append(provenance)
            return RunOutcome(
                run_id=run_id,
                status=RunStatus.PERMISSION_STOPPED,
                permission_result=permission_result,
            )

        permission = PermissionProvenance.from_result(
            self._policy,
            permission_result,
        )
        try:
            access_scope = access_scope_for(
                context,
                self._policy,
                satisfied_conditions=satisfied_conditions,
            )
        except Exception:
            return self._failed(
                run_id=run_id,
                started_at=started_at,
                context=context_provenance,
                permission_result=permission_result,
                failure_stage=FailureStage.AUTHORIZATION,
                retrieval_called=False,
                model_called=False,
            )
        if access_scope is None:
            return self._failed(
                run_id=run_id,
                started_at=started_at,
                context=context_provenance,
                permission_result=permission_result,
                failure_stage=FailureStage.AUTHORIZATION,
                retrieval_called=False,
                model_called=False,
            )

        retrieval_called = False
        try:
            retrieval_called = True
            retrieved_chunks = self._retrieval_provider.retrieve(
                query,
                access_scope,
                limit=self._configuration.retrieval_limit,
            )
            if not isinstance(retrieved_chunks, tuple):
                raise TypeError("retrieval must return a tuple")
            sources = _source_provenance(retrieved_chunks)
            model_request = ModelRequest(
                task_text=task_text,
                source_chunks=tuple(
                    ModelSourceChunk(
                        source_id=chunk.source_id.value,
                        chunk_id=chunk.chunk_id.value,
                        text=chunk.text,
                    )
                    for chunk in retrieved_chunks
                ),
            )
        except Exception:
            return self._failed(
                run_id=run_id,
                started_at=started_at,
                context=context_provenance,
                permission_result=permission_result,
                failure_stage=FailureStage.RETRIEVAL,
                retrieval_called=retrieval_called,
                model_called=False,
            )

        model_called = False
        execution: _ModelExecution | None = None
        result: ResearchResult | None
        try:
            model_called = True
            if self._execute_model is None:
                result = self._model_provider.generate(model_request)
            else:
                execution = self._execute_model(model_request)
                result = execution.result
            if not isinstance(result, ResearchResult):
                raise TypeError("model provider must return a ResearchResult")
        except Exception:
            return self._failed(
                run_id=run_id,
                started_at=started_at,
                context=context_provenance,
                permission_result=permission_result,
                failure_stage=FailureStage.MODEL,
                retrieval_called=True,
                model_called=model_called,
                sources=sources,
                execution=execution,
            )

        provenance = self._provenance(
            run_id=run_id,
            started_at=started_at,
            completed_at=self._clock(),
            status=RunStatus.GENERATED,
            context=context_provenance,
            permission=permission,
            retrieval_called=True,
            model_called=True,
            sources=sources,
            execution=execution,
        )
        self._provenance_store.append(provenance)
        return RunOutcome(
            run_id=run_id,
            status=RunStatus.GENERATED,
            permission_result=permission_result,
            result=result,
        )

    def _failed(
        self,
        *,
        run_id: RunId,
        started_at: datetime,
        context: ContextProvenance,
        permission_result: PermissionResult | None,
        failure_stage: FailureStage,
        retrieval_called: bool,
        model_called: bool,
        sources: tuple[SourceProvenance, ...] = (),
        execution: _ModelExecution | None = None,
    ) -> RunOutcome:
        permission = (
            None
            if permission_result is None
            else PermissionProvenance.from_result(self._policy, permission_result)
        )
        provenance = self._provenance(
            run_id=run_id,
            started_at=started_at,
            completed_at=self._clock(),
            status=RunStatus.FAILED,
            context=context,
            permission=permission,
            retrieval_called=retrieval_called,
            model_called=model_called,
            sources=sources,
            failure_stage=failure_stage,
            execution=execution,
        )
        self._provenance_store.append(provenance)
        return RunOutcome(
            run_id=run_id,
            status=RunStatus.FAILED,
            permission_result=permission_result,
            failure_stage=failure_stage,
        )

    def _provenance(
        self,
        *,
        run_id: RunId,
        started_at: datetime,
        completed_at: datetime,
        status: RunStatus,
        context: ContextProvenance,
        permission: PermissionProvenance | None,
        retrieval_called: bool,
        model_called: bool,
        sources: tuple[SourceProvenance, ...] = (),
        stop_reason: PermissionStopReason | None = None,
        failure_stage: FailureStage | None = None,
        execution: _ModelExecution | None = None,
    ) -> RunProvenance:
        return RunProvenance(
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            status=status,
            context=context,
            configuration=self._configuration,
            configuration_hash=self._configuration_hash,
            permission=permission,
            retrieval_called=retrieval_called,
            model_called=model_called,
            sources=sources,
            stop_reason=stop_reason,
            failure_stage=failure_stage,
            model_telemetry=None
            if execution is None
            else build_telemetry(
                execution.usage,
                execution.latency_ns,
                self._pricing,
                provider_id=self._configuration.provider_id,
                model_id=self._configuration.model_id,
                started_at=started_at,
                completed_at=completed_at,
            ),
        )


__all__ = ["RunOutcome", "RunService"]
