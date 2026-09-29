"""Governed OpenAI composition with real local authorization and provenance."""

from __future__ import annotations

import json
import socket
import sqlite3
from contextlib import closing
from dataclasses import replace
from inspect import signature
from pathlib import Path
from typing import Any

import httpx2
import pytest
from openai import OpenAI

from privilab.adapters.models import openai as adapter
from privilab.adapters.models.openai import OpenAIProviderConfig
from privilab.adapters.retrieval import SQLiteFtsRetrievalProvider
from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.application import (
    FailureStage,
    PermissionPolicy,
    RunService,
    RunStatus,
    governed_configuration_hash,
    parse_permission_policy,
)
from privilab.domain import (
    AccessScope,
    ChunkId,
    ClientContext,
    MatterContext,
    PermissionState,
    RetrievalChunk,
    RetrievalSource,
    RetrievedChunk,
    Role,
    SourceEntitlement,
    SourceId,
    SyntheticRequestContext,
    UserContext,
    UserIdentity,
    WorkflowContext,
)
from privilab.evals import EvaluationInput, GateStatus, evaluate


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def context(user: str = "user-a") -> SyntheticRequestContext:
    return SyntheticRequestContext(
        user=UserContext(UserIdentity(user), Role("role-a")),
        client=ClientContext("client-a"),
        matter=MatterContext("matter-a"),
        workflow=WorkflowContext("workflow-a"),
    )


def policy(effect: str = "ALLOW") -> PermissionPolicy:
    rules = (
        []
        if effect == "UNKNOWN"
        else [
            {
                "rule_id": "synthetic-rule",
                "effect": "ALLOW" if effect == "CONDITIONAL" else effect,
                "match": {},
                "condition_ids": ["condition-a"] if effect == "CONDITIONAL" else [],
            }
        ]
    )
    return parse_permission_policy(
        {
            "schema_version": 1,
            "policy_id": "openai-test-policy",
            "policy_version": "1",
            "synthetic": True,
            "required_context": [
                "user_id",
                "role_id",
                "client_id",
                "matter_id",
                "workflow_id",
            ],
            "rules": rules,
        }
    )


def source(name: str, user: str) -> RetrievalSource:
    source_id = SourceId(name)
    return RetrievalSource(
        source_id,
        "Synthetic test source",
        (
            RetrievalChunk(
                ChunkId(f"{name}.chunk-0"),
                source_id,
                0,
                f"boundarytoken synthetic source for {user}",
            ),
        ),
        (
            SourceEntitlement(
                source_id, user, "role-a", "client-a", "matter-a", "workflow-a"
            ),
        ),
        source_version="1",
    )


class CountingRetrieval:
    def __init__(self, provider: SQLiteFtsRetrievalProvider) -> None:
        self.provider = provider
        self.calls: list[AccessScope] = []

    def retrieve(
        self, query: str, access_scope: AccessScope, *, limit: int = 10
    ) -> tuple[RetrievedChunk, ...]:
        self.calls.append(access_scope)
        return self.provider.retrieve(query, access_scope, limit=limit)


def service(
    retrieval: CountingRetrieval,
    store: SQLiteProvenanceStore,
    *,
    effect: str = "ALLOW",
    config: OpenAIProviderConfig | None = None,
) -> RunService:
    return RunService.from_openai(
        policy=policy(effect),
        retrieval_provider=retrieval,
        provenance_store=store,
        configuration_id="synthetic-openai",
        configuration_version="1",
        retrieval_provider_id="sqlite-fts5",
        retrieval_provider_version="1",
        provider_config=config,
    )


def fake_sdk(
    monkeypatch: pytest.MonkeyPatch, *, failure: str | None = None
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        value = json.loads(request.content)
        requests.append(value)
        if failure == "timeout":
            raise httpx2.ReadTimeout("synthetic-private-timeout", request=request)
        if failure == "retry":
            return httpx2.Response(
                503, json={"error": {"message": "synthetic-private-error"}}
            )
        chunks = json.loads(value["input"])["source_chunks"]
        citations = [
            {"source_id": chunk["source_id"], "chunk_id": chunk["chunk_id"]}
            for chunk in chunks
        ]
        if failure == "citation":
            citations = [{"source_id": "unauthorized", "chunk_id": "invented"}]
        content: list[dict[str, Any]] = [
            {
                "type": "output_text",
                "text": json.dumps(
                    {"answer_text": "Synthetic answer.", "citations": citations}
                ),
                "annotations": [],
            }
        ]
        if failure == "refusal":
            content = [{"type": "refusal", "refusal": "Synthetic refusal."}]
        if failure == "malformed":
            content[0]["text"] = "synthetic malformed output"
        if failure == "missing-type":
            del content[0]["type"]
        if failure == "unknown-type":
            content[0]["type"] = "synthetic_unknown_type"
        output: list[dict[str, Any]] = [
            {
                "id": "answer",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": content,
            }
        ]
        if failure in ("reasoning-summary", "reasoning-content"):
            reasoning: dict[str, Any] = {
                "id": "reasoning",
                "type": "reasoning",
                "summary": [],
            }
            field = "summary" if failure == "reasoning-summary" else "content"
            reasoning[field] = [{"text": "synthetic-private-reasoning"}]
            output.insert(0, reasoning)
        return httpx2.Response(
            200,
            json={
                "id": "synthetic-raw-response",
                "object": "response",
                "created_at": 0,
                "model": "gpt-5.6-terra",
                "status": "incomplete" if failure == "incomplete" else "completed",
                "error": None,
                "incomplete_details": None,
                "output": output,
                "usage": {
                    "input_tokens": 13456789,
                    "output_tokens": 2,
                    "total_tokens": 13456791,
                },
            },
        )

    def client(**kwargs: Any) -> OpenAI:
        return OpenAI(
            **kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(handle))
        )

    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-integration-credential")
    monkeypatch.setattr(adapter, "OpenAI", client)
    return requests


def test_governed_path_preserves_cross_context_isolation_and_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = fake_sdk(monkeypatch)
    path = tmp_path / "provenance.sqlite3"
    with (
        closing(SQLiteFtsRetrievalProvider(tmp_path / "retrieval.sqlite3")) as index,
        closing(SQLiteProvenanceStore(path)) as store,
    ):
        index.index_source(source("source-a", "user-a"))
        index.index_source(source("source-b", "user-b"))
        retrieval = CountingRetrieval(index)
        runner = service(retrieval, store)
        first = runner.run(
            context=context(),
            task_text="Synthetic transient task.",
            query="boundarytoken",
        )
        second = runner.run(
            context=context("user-b"),
            task_text="Synthetic transient task.",
            query="boundarytoken",
        )
        assert first.status is second.status is RunStatus.GENERATED
        assert [
            json.loads(call["input"])["source_chunks"][0]["source_id"] for call in calls
        ] == ["source-a", "source-b"]
        assert "user-b" not in calls[0]["input"] and "user-a" not in calls[1]["input"]
        assert "boundarytoken" not in json.loads(calls[0]["input"])["task_text"]
        record = store.get(first.run_id)
        assert record is not None
        configuration = record.configuration
        assert configuration.provider_id == "openai-provider"
        assert configuration.provider_version == "1"
        assert configuration.model_id == "gpt-5.6-terra"
        assert configuration.model_version == "alias:gpt-5.6-terra"
        assert configuration.model_content_hash is None
        options = dict(configuration.options)
        assert options["sdk_version"] == "3.19.2"
        assert options["timeout_seconds"] == "30.0"
        assert options["max_retries"] == "2"
        assert options["max_retry_delay_seconds"] == "5.0"
        assert record.configuration_hash == governed_configuration_hash(
            configuration, policy()
        )
        changed = replace(
            configuration,
            options=OpenAIProviderConfig(timeout_seconds=7).configuration_options(),
        )
        assert record.configuration_hash != governed_configuration_hash(
            changed, policy()
        )
        assert len(retrieval.calls) == 2
    with closing(SQLiteProvenanceStore(path)) as reopened:
        assert reopened.get(first.run_id) == record
    with sqlite3.connect(path) as db:
        stored = "\n".join(db.iterdump())
    for excluded in (
        "synthetic-integration-credential",
        "Synthetic transient task.",
        "boundarytoken",
        "Synthetic answer.",
        "synthetic-raw-response",
        "13456789",
        "input_tokens",
        "cache_write_tokens",
    ):
        assert excluded not in stored


@pytest.mark.parametrize("effect", ["BLOCK", "UNKNOWN", "CONDITIONAL"])
def test_permission_stops_before_retrieval_credentials_or_model(
    effect: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(**kwargs: Any) -> OpenAI:
        raise AssertionError("SDK construction must not happen")

    monkeypatch.setattr(adapter, "OpenAI", forbidden)
    with (
        closing(SQLiteFtsRetrievalProvider(tmp_path / "retrieval.sqlite3")) as index,
        closing(SQLiteProvenanceStore(tmp_path / "provenance.sqlite3")) as store,
    ):
        retrieval = CountingRetrieval(index)
        runner = service(retrieval, store, effect=effect)
        outcome = runner.run(
            context=context(), task_text="Synthetic task.", query="boundarytoken"
        )
        assert outcome.status is RunStatus.PERMISSION_STOPPED
        assert outcome.permission_result is not None
        assert outcome.permission_result.state is PermissionState(effect)
        assert retrieval.calls == []
        record = store.get(outcome.run_id)
        assert record is not None
        assert record.model_called is record.retrieval_called is False


@pytest.mark.parametrize(
    "failure",
    [
        "timeout",
        "retry",
        "missing-key",
        "refusal",
        "malformed",
        "incomplete",
        "missing-type",
        "unknown-type",
        "reasoning-summary",
        "reasoning-content",
    ],
)
def test_provider_failures_reach_existing_model_boundary(
    failure: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = fake_sdk(monkeypatch, failure=failure)
    if failure == "missing-key":
        monkeypatch.delenv("OPENAI_API_KEY")
    with (
        closing(SQLiteFtsRetrievalProvider(tmp_path / "retrieval.sqlite3")) as index,
        closing(SQLiteProvenanceStore(tmp_path / "provenance.sqlite3")) as store,
    ):
        index.index_source(source("source-a", "user-a"))
        outcome = service(CountingRetrieval(index), store).run(
            context=context(), task_text="Synthetic task.", query="boundarytoken"
        )
        assert outcome.status is RunStatus.FAILED
        assert outcome.failure_stage is FailureStage.MODEL
        assert outcome.result is None
        record = store.get(outcome.run_id)
        assert record is not None and record.failure_stage is FailureStage.MODEL
        assert record.model_called is record.retrieval_called is True
        assert [item.source_id for item in record.sources] == ["source-a"]
        assert "synthetic-private" not in repr(record)
        expected = (
            0
            if failure == "missing-key"
            else 3
            if failure in ("timeout", "retry")
            else 1
        )
        assert len(calls) == expected
        assert (
            evaluate(EvaluationInput(outcome, record)).gate.status is GateStatus.BLOCK
        )


def test_generated_unsupported_citations_still_fail_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_sdk(monkeypatch, failure="citation")
    with (
        closing(SQLiteFtsRetrievalProvider(tmp_path / "retrieval.sqlite3")) as index,
        closing(SQLiteProvenanceStore(tmp_path / "provenance.sqlite3")) as store,
    ):
        index.index_source(source("source-a", "user-a"))
        outcome = service(CountingRetrieval(index), store).run(
            context=context(), task_text="Synthetic task.", query="boundarytoken"
        )
        assert outcome.status is RunStatus.GENERATED
        record = store.get(outcome.run_id)
        assert record is not None
        assert (
            evaluate(EvaluationInput(outcome, record)).gate.status is GateStatus.BLOCK
        )


def test_production_composition_does_not_accept_identity_or_client_substitution() -> (
    None
):
    parameters = set(signature(RunService.from_openai).parameters)
    assert {
        "model_provider",
        "provider_id",
        "provider_version",
        "model_id",
        "model_version",
        "model_content_hash",
        "api_key",
        "base_url",
        "client",
        "_client_factory",
        "options",
    }.isdisjoint(parameters)
