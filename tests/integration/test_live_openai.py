"""Exercise the actual live runner with synthetic SDK responses, never networking."""

from __future__ import annotations

import json
import logging
import shutil
import socket
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_model_telemetry import FakeClock, price, sdk
from test_model_telemetry import offline as offline

from privilab.adapters.models import openai as adapter
from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.application import RunStatus
from privilab.application.telemetry import (
    CostStatus,
    CostUnavailableReason,
    PricingInputState,
)
from privilab.evals import live_openai

ROOT = Path(__file__).parents[2]


@pytest.fixture
def case_root(tmp_path: Path) -> Path:
    for directory in ("contexts", "corpus"):
        shutil.copytree(
            ROOT / "fixtures" / directory, tmp_path / "fixtures" / directory
        )
    return tmp_path


def test_real_live_runner_opt_in_does_not_override_source_only_hold(
    case_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRIVILAB_LIVE_EVAL", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key-cannot-lift-hold")
    monkeypatch.delenv("PRIVILAB_PRICING_EVIDENCE_FILE", raising=False)
    constructed: list[bool] = []

    def forbidden(**kwargs: object) -> None:
        constructed.append(True)
        raise AssertionError("live runner must not construct an HTTP client")

    monkeypatch.setattr(adapter, "OpenAI", forbidden)
    evidence = live_openai.run_live(case_root)
    assert evidence.passed is False
    assert evidence.run.status is RunStatus.FAILED
    assert constructed == []


@pytest.mark.parametrize("pricing", ["absent", "missing-file", "invalid", "valid"])
def test_governed_runner_persists_reconstructable_evidence(
    pricing: str,
    case_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = sdk(monkeypatch, FakeClock())
    monkeypatch.setenv("PRIVILAB_LIVE_EVAL", "1")
    monkeypatch.delenv("PRIVILAB_PRICING_EVIDENCE_FILE", raising=False)
    pricing_path = case_root / ".local" / "pricing.json"
    if pricing != "absent":
        monkeypatch.setenv("PRIVILAB_PRICING_EVIDENCE_FILE", str(pricing_path))
    if pricing in ("invalid", "valid"):
        pricing_path.parent.mkdir()
        contents = "raw-malformed-pricing-sentinel"
        if pricing == "valid":
            snapshot = price().snapshot
            assert snapshot is not None
            now = datetime.now(UTC)
            contents = replace(
                snapshot,
                retrieved_at=now - timedelta(minutes=1),
                effective_at=None,
                expires_at=now + timedelta(days=1),
            ).canonical_json()
        pricing_path.write_text(contents, encoding="utf-8")
    caplog.set_level(logging.DEBUG)
    run_live = live_openai.run_live
    monkeypatch.setattr(live_openai, "run_live", lambda: run_live(case_root))
    live_openai.main()
    output = capsys.readouterr()
    summary = json.loads(output.out)
    assert summary["status"] == "GENERATED"
    assert len(calls) == 1
    assert "synthetic-trade-notice-001" in calls[0]["input"]
    assert "synthetic-trade-notice-chunk-001" in calls[0]["input"]
    assert "synthetic-user-001" not in calls[0]["input"]
    database = Path(summary["database_path"])
    assert database == case_root / ".local/live-eval/provenance.sqlite3"
    store = SQLiteProvenanceStore(database)
    try:
        ids = store.recent_run_ids()
        assert len(ids) == 1
        run = store.get(ids[0])
        assert run is not None and run.status is RunStatus.GENERATED
        assert run.model_telemetry is not None
        evaluation = store.get_evaluation(ids[0])
        assert evaluation is not None and evaluation.gate_status.value == "PASS"
        assert store.get_review(ids[0]) is None
        assert dict(run.configuration.options)["live_case_id"] == live_openai.CASE_ID
        if pricing == "valid":
            assert run.model_telemetry.cost_status is CostStatus.CALCULATED
            assert summary["cost_amount_decimal"] == "0.000269"
        else:
            expected = (
                CostUnavailableReason.PRICING_EVIDENCE_INVALID
                if pricing == "invalid"
                else CostUnavailableReason.PRICING_EVIDENCE_MISSING
            )
            assert run.model_telemetry.cost_unavailable_reason is expected
            assert summary["cost_amount_decimal"] is None
    finally:
        store.close()
    with sqlite3.connect(database) as connection:
        dump = "\n".join(connection.iterdump())
    for sentinel in (
        "synthetic-credential-sentinel",
        "raw-response-sentinel",
        "generated-answer-sentinel",
        "raw-malformed-pricing-sentinel",
        "Synthetic notice text",
        "Briefly summarize",
    ):
        assert sentinel not in output.out + output.err + caplog.text + dump


@pytest.mark.parametrize(
    "source_url",
    [
        "https://localhost/private-pricing.json",
        "https://127.0.0.1/private",
        "https://10.0.0.1/private",
        "https://169.254.169.254/private",
        "https://[::1]/private",
        "https://example.com:99999/pricing",
        "https://openai.com:99999/pricing",
        "https://openai.com:private-port/pricing",
        "https://[private]/pricing",
        "https://openai.com:8443/pricing",
        "https://openai.com.evil.example/pricing",
        "https://evilopenai.com/pricing",
        "https://user:secret@openai.com/pricing",
        "https://openai.com/pricing?secret=private",
        "https://openai.com/pricing#private",
    ],
)
def test_rejected_source_allows_generation_without_leaking_evidence(
    source_url: str,
    case_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    def no_dns(*args: object, **kwargs: object) -> None:
        raise AssertionError("pricing sources must not be resolved")

    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex"):
        monkeypatch.setattr(socket, name, no_dns)
    calls = sdk(monkeypatch, FakeClock())
    monkeypatch.setenv("PRIVILAB_LIVE_EVAL", "1")
    pricing_path = case_root / "private-pricing-input-sentinel.json"
    snapshot = price().snapshot
    assert snapshot is not None
    raw = json.loads(snapshot.canonical_json())
    raw["source_url"] = source_url
    pricing_path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setenv("PRIVILAB_PRICING_EVIDENCE_FILE", str(pricing_path))
    envelope = live_openai.load_pricing(str(pricing_path))
    assert envelope.state is PricingInputState.INVALID
    assert envelope.snapshot is None and envelope.configuration_options() == ()
    caplog.set_level(logging.DEBUG)
    original = live_openai.run_live
    monkeypatch.setattr(live_openai, "run_live", lambda: original(case_root))
    live_openai.main()
    output = capsys.readouterr()
    summary = json.loads(output.out)
    assert len(calls) == 1 and summary["status"] == "GENERATED"
    assert summary["cost_status"] == "NOT_CALCULATED"
    assert summary["cost_amount_decimal"] is None
    assert summary["cost_unavailable_reason"] == "PRICING_EVIDENCE_INVALID"
    assert summary["pricing_source_id"] is None
    assert summary["pricing_snapshot_hash"] is None
    assert summary["pricing_snapshot_schema_version"] is None
    database = Path(summary["database_path"])
    store = SQLiteProvenanceStore(database)
    try:
        run = store.get(store.recent_run_ids()[0])
        assert run is not None and run.status is RunStatus.GENERATED
        assert run.model_telemetry is not None
        assert run.model_telemetry.pricing_snapshot is None
        assert run.model_telemetry.cost_status is CostStatus.NOT_CALCULATED
        assert run.model_telemetry.cost_amount_decimal is None
        assert (
            run.model_telemetry.cost_unavailable_reason
            is CostUnavailableReason.PRICING_EVIDENCE_INVALID
        )
        assert not any("pricing" in key for key, _ in run.configuration.options)
        evaluation = store.get_evaluation(run.run_id)
        assert evaluation is not None and evaluation.gate_status.value == "PASS"
        assert store.get_review(run.run_id) is None
    finally:
        store.close()
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT pricing_snapshot_json FROM model_telemetry"
        ).fetchall() == [(None,)]
        dump = "\n".join(connection.iterdump())
    captured = output.out + output.err + caplog.text + dump + repr(run) + repr(envelope)
    for sentinel in (
        source_url,
        str(pricing_path),
        "private-pricing-input-sentinel",
        "private-port",
        "Port out of range",
        "Port could not be cast",
        "does not appear to be an IPv4 or IPv6 address",
        "Traceback",
    ):
        assert sentinel not in captured
    assert all(record.exc_info is None for record in caplog.records)


def test_missing_credentials_fail_safely_after_model_stage(
    case_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PRIVILAB_LIVE_EVAL", "1")
    monkeypatch.delenv("PRIVILAB_PRICING_EVIDENCE_FILE", raising=False)
    original = live_openai.run_live
    monkeypatch.setattr(live_openai, "run_live", lambda: original(case_root))
    with pytest.raises(
        SystemExit, match="live smoke validation pending approved local execution"
    ):
        live_openai.main()
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "FAILED"
    assert summary["usage"] is None
    assert summary["provider_latency_ns"] >= 0
    assert summary["cost_amount_decimal"] is None


def test_invalid_fixture_fails_before_credentials(
    case_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = sdk(monkeypatch, FakeClock())
    monkeypatch.setenv("PRIVILAB_LIVE_EVAL", "1")
    (case_root / "fixtures/corpus/synthetic_trade_notice_v1.json").write_text(
        "tampered", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="content does not match"):
        live_openai.run_live(case_root)
    assert calls == []
    assert not (case_root / ".local").exists()


def test_unreadable_pricing_yields_invalid_without_retaining_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise PermissionError("private-file-error-sentinel")

    monkeypatch.setattr(Path, "open", denied)
    result = live_openai.load_pricing("synthetic-pricing.json")
    assert result.state is PricingInputState.INVALID and result.snapshot is None
    assert "private" not in repr(result)


@pytest.mark.parametrize("contents", [b"\xff", b"x" * 65537, b"{}", b"[[]"])
def test_malformed_pricing_files_are_invalid(contents: bytes, tmp_path: Path) -> None:
    path = tmp_path / "pricing.json"
    path.write_bytes(contents)
    assert live_openai.load_pricing(str(path)).state is PricingInputState.INVALID
