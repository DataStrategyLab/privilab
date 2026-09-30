"""Exercise the actual live runner with synthetic SDK responses, never networking."""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_model_telemetry import FakeClock, price, sdk
from test_model_telemetry import offline as offline

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
