"""Governed telemetry against real local retrieval/storage and an offline SDK."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2
import pytest
from openai import OpenAI
from test_openai_run_service import CountingRetrieval, context, policy, source

from privilab.adapters.models import openai as adapter
from privilab.adapters.models.openai import OpenAIProviderConfig
from privilab.adapters.retrieval import SQLiteFtsRetrievalProvider
from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.application import FailureStage, RunProvenance, RunService, RunStatus
from privilab.application.telemetry import (
    CALCULATION_RULE,
    UNIT_BASIS,
    BillingAttestation,
    BillingMode,
    CostUnavailableReason,
    ModelUsage,
    PricingInput,
    PricingInputState,
    PricingSnapshot,
    ProcessingMode,
    TokenRates,
)

STAMP = datetime(2026, 9, 30, 12, tzinfo=UTC)


def price() -> PricingInput:
    return PricingInput(
        PricingInputState.VALID,
        PricingSnapshot(
            "1",
            "openai-provider",
            "gpt-5.6-terra",
            ProcessingMode.STANDARD,
            "synthetic-price",
            "https://openai.com/synthetic-pricing-test-fixture",
            STAMP,
            STAMP,
            STAMP + timedelta(seconds=5),
            "USD",
            UNIT_BASIS,
            100,
            TokenRates("2.00", "0.20", "3.00", "10.00"),
            TokenRates("4.00", "0.40", "6.00", "20.00"),
            CALCULATION_RULE,
            BillingAttestation(BillingMode.STANDARD_SYNCHRONOUS, "operator", "1"),
        ),
    )


class FakeClock:
    def __init__(self) -> None:
        self.nanoseconds = 1000

    def monotonic_ns(self) -> int:
        return self.nanoseconds

    def sleep(self, seconds: float) -> None:
        self.nanoseconds += int(seconds * 1_000_000_000)


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def sdk(
    monkeypatch: pytest.MonkeyPatch,
    clock: FakeClock,
    *,
    failure: str | None = None,
    usage: str = "full",
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        clock.nanoseconds += 10
        payload = json.loads(request.content)
        calls.append(payload)
        if failure == "timeout":
            raise httpx2.ReadTimeout("private-error-sentinel", request=request)
        if failure == "exhaust" or (failure == "retry" and len(calls) == 1):
            return httpx2.Response(
                503,
                headers={"Retry-After": "2"},
                json={"error": {"message": "private-error-sentinel"}},
            )
        chunks = json.loads(payload["input"])["source_chunks"]
        body: dict[str, Any] = {
            "id": "raw-response-sentinel",
            "object": "response",
            "created_at": 0,
            "model": "gpt-5.6-terra",
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "output": [
                {
                    "id": "answer",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "annotations": [],
                            "text": json.dumps(
                                {
                                    "answer_text": "generated-answer-sentinel",
                                    "citations": [
                                        {
                                            "source_id": c["source_id"],
                                            "chunk_id": c["chunk_id"],
                                        }
                                        for c in chunks
                                    ],
                                }
                            ),
                        }
                    ],
                }
            ],
        }
        if usage != "missing":
            body["usage"] = (
                {}
                if usage == "empty"
                else {
                    "input_tokens": True
                    if usage == "invalid"
                    else 2**63
                    if usage == "overflow"
                    else 100,
                    "output_tokens": 10,
                    "total_tokens": 110,
                    "input_tokens_details": {
                        "cached_tokens": 20,
                        "cache_write_tokens": 5,
                    },
                    "output_tokens_details": {"reasoning_tokens": 2},
                }
            )
        return httpx2.Response(200, json=body)

    def client(**kwargs: Any) -> OpenAI:
        return OpenAI(
            **kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(handle))
        )

    original_provider = adapter.OpenAIProvider

    def provider(settings: OpenAIProviderConfig) -> adapter.OpenAIProvider:
        return original_provider(settings, _sleep=clock.sleep)

    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-credential-sentinel")
    monkeypatch.setattr(adapter, "OpenAI", client)
    monkeypatch.setattr(adapter, "OpenAIProvider", provider)
    return calls


def execute(
    path: Path,
    clock: FakeClock,
    pricing: PricingInput | None = None,
    *,
    effect: str = "ALLOW",
    finish: datetime = STAMP + timedelta(seconds=5),
) -> RunProvenance:
    with (
        closing(SQLiteFtsRetrievalProvider(":memory:")) as index,
        closing(SQLiteProvenanceStore(path)) as store,
    ):
        index.index_source(source("source-a", "user-a"))
        index.index_source(source("unauthorized-source", "user-b"))
        stamps = iter((STAMP, finish))
        runner = RunService.from_openai(
            policy=policy(effect),
            retrieval_provider=CountingRetrieval(index),
            provenance_store=store,
            configuration_id="synthetic-telemetry",
            configuration_version="1",
            retrieval_provider_id="sqlite-fts5",
            retrieval_provider_version="1",
            monotonic_ns=clock.monotonic_ns,
            clock=lambda: next(stamps),
            pricing=PricingInput() if pricing is None else pricing,
        )
        outcome = runner.run(
            context=context(),
            task_text="transient-task-sentinel",
            query="boundarytoken",
        )
        record = store.get(outcome.run_id)
        assert record is not None
        assert record.status == outcome.status
        with pytest.raises(StopIteration):
            next(stamps)  # Exactly the two timestamps persisted, no pricing clock read.
        return record


@pytest.mark.parametrize(
    "failure, latency, status",
    [
        (None, 10, RunStatus.GENERATED),
        ("retry", 2_000_000_020, RunStatus.GENERATED),
        ("exhaust", 4_000_000_030, RunStatus.FAILED),
        ("timeout", 1_500_000_030, RunStatus.FAILED),
    ],
)
def test_complete_call_latency_and_roundtrip(
    failure: str | None,
    latency: int,
    status: RunStatus,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    calls = sdk(monkeypatch, clock, failure=failure)
    path = tmp_path / "evidence.sqlite3"
    record = execute(path, clock, price())
    assert record.status is status
    assert record.started_at == STAMP and record.completed_at == STAMP + timedelta(
        seconds=5
    )
    telemetry = record.model_telemetry
    assert telemetry is not None and telemetry.provider_latency_ns == latency
    if status is RunStatus.GENERATED:
        assert telemetry.usage == ModelUsage(100, 10, 110, 20, 5, 2)
        assert telemetry.cost_amount_decimal == "0.000269"
    else:
        assert record.failure_stage is FailureStage.MODEL
        assert telemetry.usage is None
        assert (
            telemetry.cost_unavailable_reason
            is CostUnavailableReason.USAGE_EVIDENCE_INSUFFICIENT
        )
    assert all("unauthorized-source" not in call["input"] for call in calls)
    assert "source-a" in calls[0]["input"]
    with closing(SQLiteProvenanceStore(path)) as store:
        assert store.get(record.run_id) == record
    with sqlite3.connect(path) as db:
        dump = "\n".join(db.iterdump())
    for sentinel in (
        "synthetic-credential-sentinel",
        "transient-task-sentinel",
        "boundarytoken",
        "generated-answer-sentinel",
        "raw-response-sentinel",
        "private-error-sentinel",
    ):
        assert sentinel not in dump
    options = dict(record.configuration.options)
    snapshot = price().snapshot
    assert snapshot is not None
    assert options["pricing_snapshot_hash"] == snapshot.content_hash
    assert "pricing_snapshot_schema_version" in options
    assert all(
        key not in options
        for key in ("source_url", "billing_attestation", "input_rate", "expires_at")
    )


@pytest.mark.parametrize("usage", ["missing", "empty", "invalid", "overflow"])
def test_missing_and_malformed_usage_keep_latency(
    usage: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = FakeClock()
    sdk(monkeypatch, clock, usage=usage)
    record = execute(tmp_path / "evidence.sqlite3", clock, price())
    assert record.status is (
        RunStatus.FAILED if usage in ("invalid", "overflow") else RunStatus.GENERATED
    )
    telemetry = record.model_telemetry
    assert telemetry is not None and telemetry.provider_latency_ns == 10
    assert telemetry.usage == (ModelUsage() if usage == "empty" else None)
    assert (
        telemetry.cost_unavailable_reason
        is CostUnavailableReason.USAGE_EVIDENCE_INSUFFICIENT
    )


@pytest.mark.parametrize(
    "pricing, reason",
    [
        (None, CostUnavailableReason.PRICING_EVIDENCE_MISSING),
        (
            PricingInput(PricingInputState.INVALID),
            CostUnavailableReason.PRICING_EVIDENCE_INVALID,
        ),
    ],
)
def test_pricing_unavailable_does_not_abort_generation(
    pricing: PricingInput | None,
    reason: CostUnavailableReason,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    sdk(monkeypatch, clock)
    record = execute(tmp_path / "evidence.sqlite3", clock, pricing)
    assert record.status is RunStatus.GENERATED
    assert record.model_telemetry is not None
    assert record.model_telemetry.cost_unavailable_reason is reason
    assert record.model_telemetry.pricing_snapshot is None
    assert not any(
        name.startswith("pricing_") for name, _ in record.configuration.options
    )


@pytest.mark.parametrize("effect", ["BLOCK", "UNKNOWN", "CONDITIONAL"])
def test_permission_stop_never_reads_credentials_or_timing(
    effect: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = type(os.environ).__getitem__

    def guard(self: Any, key: str) -> str:
        assert key != "OPENAI_API_KEY"
        return original(self, key)

    monkeypatch.setattr(type(os.environ), "__getitem__", guard)
    clock = FakeClock()
    record = execute(tmp_path / "evidence.sqlite3", clock, effect=effect)
    assert record.status is RunStatus.PERMISSION_STOPPED
    assert record.model_telemetry is None
    assert not record.model_called and not record.retrieval_called
    assert clock.nanoseconds == 1000


def test_expiry_uses_persisted_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = FakeClock()
    sdk(monkeypatch, clock)
    end = STAMP + timedelta(seconds=5, microseconds=1)
    record = execute(tmp_path / "evidence.sqlite3", clock, price(), finish=end)
    assert record.completed_at == end
    assert record.model_telemetry is not None
    assert (
        record.model_telemetry.cost_unavailable_reason
        is CostUnavailableReason.PRICING_EVIDENCE_NOT_APPLICABLE
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE model_telemetry SET latency_ns=0",
        "UPDATE model_telemetry SET run_id='another-run'",
        "DELETE FROM model_telemetry",
        "INSERT OR REPLACE INTO model_telemetry SELECT * FROM model_telemetry",
    ],
)
def test_telemetry_append_only(
    mutation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = FakeClock()
    sdk(monkeypatch, clock)
    path = tmp_path / "evidence.sqlite3"
    record = execute(path, clock, price())
    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(mutation)
    with closing(SQLiteProvenanceStore(path)) as store:
        assert store.get(record.run_id) == record


def test_finalized_no_telemetry_cannot_be_backfilled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = FakeClock()
    sdk(monkeypatch, clock)
    path = tmp_path / "evidence.sqlite3"
    first = execute(path, clock)
    second = replace(
        first,
        run_id=type(first.run_id)("historical-no-telemetry"),
        model_telemetry=None,
    )
    with closing(SQLiteProvenanceStore(path)) as store:
        store.append(second)
        assert store.get(second.run_id) == second
    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO model_telemetry SELECT ?, latency_ns, latency_scope, "
                "usage_present, input_tokens, output_tokens, total_tokens, "
                "cached_input_tokens, cache_write_tokens, reasoning_tokens, "
                "cost_status, cost_amount_decimal, cost_unavailable_reason, "
                "pricing_snapshot_json FROM model_telemetry",
                (second.run_id.value,),
            )


def test_pre_dsl116_schema_rejected_without_repair(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    with closing(SQLiteProvenanceStore(path)):
        pass
    # All previous tables and triggers are unchanged. Removing the new table
    # (and its own triggers) reconstructs precisely the baseline schema.
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE model_telemetry")
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="incompatible"):
        SQLiteProvenanceStore(path)
    assert path.read_bytes() == before


def test_snapshot_hash_must_match_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = FakeClock()
    sdk(monkeypatch, clock)
    record = execute(tmp_path / "evidence.sqlite3", clock, price())
    configuration = replace(record.configuration, options=())
    with pytest.raises(ValueError, match="snapshot does not match"):
        replace(record, configuration=configuration)


@pytest.mark.parametrize(
    "field, value",
    [
        ("cost_amount_decimal", "0.00"),
        ("pricing_snapshot_json", '{"raw_payload":"must-not-be-accepted"}'),
        ("input_tokens", 1.5),
    ],
)
def test_corrupt_evidence_rejected_on_read(
    field: str, value: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = FakeClock()
    sdk(monkeypatch, clock)
    path = tmp_path / "evidence.sqlite3"
    record = execute(path, clock, price())
    with sqlite3.connect(path) as connection:
        sql = connection.execute(
            "SELECT sql FROM sqlite_schema WHERE name='prevent_model_telemetry_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER prevent_model_telemetry_update")
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute(f"UPDATE model_telemetry SET {field}=?", (value,))
        connection.execute(sql)
    with closing(SQLiteProvenanceStore(path)) as store:
        with pytest.raises(ValueError):
            store.get(record.run_id)
