"""Synthetic pricing and immutable evidence; no vendor prices or live calls."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import localcontext
from typing import Any

import pytest

from privilab.application.telemetry import (
    CALCULATION_RULE,
    LATENCY_SCOPE,
    TOKEN_FIELDS,
    UNIT_BASIS,
    BillingAttestation,
    BillingMode,
    CostStatus,
    ModelTelemetry,
    ModelUsage,
    PricingInput,
    PricingInputState,
    PricingSnapshot,
    ProcessingMode,
    TokenRates,
    build_telemetry,
)
from privilab.application.telemetry import (
    CostUnavailableReason as Reason,
)

START = datetime(2026, 9, 30, 12, tzinfo=UTC)
END = START + timedelta(seconds=5)
USAGE = ModelUsage(100, 10, 110, 20, 5, 2)


def snapshot() -> PricingSnapshot:
    return PricingSnapshot(
        "1",
        "openai-provider",
        "gpt-5.6-terra",
        ProcessingMode.STANDARD,
        "synthetic-pricing",
        "https://example.invalid/synthetic-pricing",
        START,
        None,
        END,
        "USD",
        UNIT_BASIS,
        100,
        TokenRates("2.00", "0.20", "3.00", "10.00"),
        TokenRates("4.00", "0.40", "6.00", "20.00"),
        CALCULATION_RULE,
        BillingAttestation(BillingMode.STANDARD_SYNCHRONOUS, "operator", "1"),
    )


def calculate(
    usage: ModelUsage | None = USAGE, pricing: PricingInput | None = None, **kwargs: Any
) -> ModelTelemetry:
    return build_telemetry(
        usage,
        123,
        pricing
        if pricing is not None
        else PricingInput(PricingInputState.VALID, snapshot()),
        provider_id="openai-provider",
        model_id="gpt-5.6-terra",
        started_at=START,
        completed_at=END,
        **kwargs,
    )


def test_exact_short_context_formula_and_evidence() -> None:
    result = calculate()
    assert result.cost_status is CostStatus.CALCULATED
    assert result.cost_amount_decimal == "0.000269"
    assert result.cost_unavailable_reason is None
    assert result.usage == USAGE
    assert result.provider_latency_ns == 123 and result.latency_scope == LATENCY_SCOPE
    assert (
        calculate(replace(USAGE, reasoning_tokens=10)).cost_amount_decimal
        == result.cost_amount_decimal
    )


@pytest.mark.parametrize(
    "usage, amount",
    [
        (ModelUsage(100, 0, None, 0, 0), "0.0002"),
        (ModelUsage(100, 0, None, 100, 0), "0.00002"),
        (ModelUsage(100, 0, None, 0, 100), "0.0003"),
        (ModelUsage(0, 10, None, 0, 0), "0.0001"),
        (ModelUsage(0, 0, 0, 0, 0, 0), "0.00"),
        (ModelUsage(101, 10, 111, 20, 5, 2), "0.000542"),
    ],
)
def test_usage_dimensions_and_long_context(usage: ModelUsage, amount: str) -> None:
    assert calculate(usage).cost_amount_decimal == amount


@pytest.mark.parametrize(
    "field",
    ["input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens"],
)
def test_missing_required_counts_are_never_inferred(field: str) -> None:
    result = calculate(replace(USAGE, **{field: None}))
    assert result.cost_amount_decimal is None
    assert result.cost_unavailable_reason is Reason.USAGE_EVIDENCE_INSUFFICIENT


@pytest.mark.parametrize(
    "usage",
    [
        replace(USAGE, cached_input_tokens=99),
        replace(USAGE, cache_write_tokens=81),
        replace(USAGE, total_tokens=999),
        replace(USAGE, reasoning_tokens=11),
    ],
)
def test_inconsistent_evidence_fails_cost(usage: ModelUsage) -> None:
    assert (
        calculate(usage).cost_unavailable_reason is Reason.USAGE_EVIDENCE_INCONSISTENT
    )


def test_missing_usage_and_optional_counts() -> None:
    result = calculate(None)
    assert (
        result.usage is None
        and result.cost_unavailable_reason is Reason.USAGE_EVIDENCE_INSUFFICIENT
    )
    assert (
        calculate(
            replace(USAGE, total_tokens=None, reasoning_tokens=None)
        ).cost_amount_decimal
        == "0.000269"
    )


@pytest.mark.parametrize(
    "state, reason",
    [
        (PricingInputState.MISSING, Reason.PRICING_EVIDENCE_MISSING),
        (PricingInputState.INVALID, Reason.PRICING_EVIDENCE_INVALID),
    ],
)
def test_unavailable_envelopes(state: PricingInputState, reason: Reason) -> None:
    result = calculate(None, PricingInput(state))
    assert result.cost_status is CostStatus.NOT_CALCULATED
    assert result.cost_amount_decimal is None
    assert result.pricing_snapshot is None
    assert result.cost_unavailable_reason is reason


@pytest.mark.parametrize(
    "change",
    [
        {"retrieved_at": START + timedelta(microseconds=1)},
        {"effective_at": START + timedelta(microseconds=1)},
        {"expires_at": END - timedelta(microseconds=1)},
        {"provider_id": "different-provider"},
        {"model_id": "different-model"},
    ],
)
def test_non_applicable_pricing(change: dict[str, Any]) -> None:
    price = replace(snapshot(), **change)
    result = calculate(None, PricingInput(PricingInputState.VALID, price))
    assert result.cost_unavailable_reason is Reason.PRICING_EVIDENCE_NOT_APPLICABLE
    assert result.pricing_snapshot == price


def test_exact_temporal_boundaries_and_timezone_normalization() -> None:
    offset = timezone(timedelta(hours=3))
    price = replace(
        snapshot(),
        retrieved_at=START.astimezone(offset),
        effective_at=START,
        expires_at=END.astimezone(offset),
    )
    assert (
        calculate(pricing=PricingInput(PricingInputState.VALID, price)).cost_status
        is CostStatus.CALCULATED
    )


@pytest.mark.parametrize("mode", list(ProcessingMode))
def test_processing_mode_is_never_inferred(mode: ProcessingMode) -> None:
    price = replace(snapshot(), processing_mode=mode)
    result = calculate(pricing=PricingInput(PricingInputState.VALID, price))
    assert result.cost_unavailable_reason is (
        None if mode is ProcessingMode.STANDARD else Reason.BILLING_MODE_UNCONFIRMED
    )


@pytest.mark.parametrize("mode", list(BillingMode))
def test_bounded_attestation_modes(mode: BillingMode) -> None:
    price = replace(
        snapshot(), billing_attestation=BillingAttestation(mode, "operator", "1")
    )
    result = calculate(pricing=PricingInput(PricingInputState.VALID, price))
    assert result.cost_unavailable_reason is (
        None
        if mode is BillingMode.STANDARD_SYNCHRONOUS
        else Reason.BILLING_MODE_UNCONFIRMED
    )


def test_reason_precedence_and_missing_optional_attestation() -> None:
    price = replace(
        snapshot(),
        billing_attestation=None,
        provider_id="wrong",
        calculation_rule_version="unsupported",
    )
    envelope = PricingInput.from_json(price.canonical_json())
    assert envelope.state is PricingInputState.VALID
    assert (
        calculate(None, envelope).cost_unavailable_reason
        is Reason.BILLING_MODE_UNCONFIRMED
    )
    price = replace(price, billing_attestation=snapshot().billing_attestation)
    assert (
        calculate(
            None, PricingInput(PricingInputState.VALID, price)
        ).cost_unavailable_reason
        is Reason.PRICING_EVIDENCE_NOT_APPLICABLE
    )
    price = replace(price, provider_id="openai-provider")
    assert (
        calculate(
            None, PricingInput(PricingInputState.VALID, price)
        ).cost_unavailable_reason
        is Reason.PRICING_RULE_UNSUPPORTED
    )
    incomplete = replace(USAGE, output_tokens=None, cached_input_tokens=200)
    assert (
        calculate(incomplete).cost_unavailable_reason
        is Reason.USAGE_EVIDENCE_INSUFFICIENT
    )


@pytest.mark.parametrize("field", ["unit_basis", "calculation_rule_version"])
def test_unknown_rules(field: str) -> None:
    change: dict[str, Any] = {field: "unsupported"}
    price = replace(snapshot(), **change)
    assert (
        calculate(
            pricing=PricingInput(PricingInputState.VALID, price)
        ).cost_unavailable_reason
        is Reason.PRICING_RULE_UNSUPPORTED
    )


@pytest.mark.parametrize("field", TOKEN_FIELDS)
@pytest.mark.parametrize("value", [-1, True, 1.5, "1", 2**63])
def test_bad_counts_rejected(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        ModelUsage(**{field: value})


@pytest.mark.parametrize(
    "field, value",
    [
        ("schema_version", 1),
        ("schema_version", "2"),
        ("unexpected", "raw-private"),
        ("processing_mode", "not-an-enum"),
        ("context_threshold_input_tokens", True),
        ("retrieved_at", "2026-09-30"),
        ("retrieved_at", "2026-09-30T12:00:00"),
        ("source_url", "https://secret@example.invalid"),
        ("source_url", "https://example.invalid/?secret=private"),
        (
            "short_context",
            {
                "input": 2.0,
                "cached_input": "0.20",
                "cache_write": "3.00",
                "output": "10.00",
            },
        ),
        ("billing_attestation", None),
        ("billing_attestation", {}),
        (
            "billing_attestation",
            {
                "billing_mode_attestation": "STANDARD_SYNCHRONOUS",
                "attested_by": "named-person",
                "attestation_version": "1",
            },
        ),
        (
            "billing_attestation",
            {
                "billing_mode_attestation": "STANDARD_SYNCHRONOUS",
                "attested_by": "operator",
                "attestation_version": "2",
            },
        ),
    ],
)
def test_invalid_pricing_is_content_free(field: str, value: Any) -> None:
    raw = json.loads(snapshot().canonical_json())
    raw[field] = value
    envelope = PricingInput.from_json(json.dumps(raw))
    assert envelope == PricingInput(PricingInputState.INVALID)
    assert envelope.configuration_options() == ()


@pytest.mark.parametrize(
    "payload",
    ["{", "[]", "null", '{"schema_version":"1","schema_version":"1"}', "[" * 1100],
)
def test_bad_json_returns_invalid_envelope(payload: str) -> None:
    assert PricingInput.from_json(payload).state is PricingInputState.INVALID


def test_canonical_snapshot_decimal_roundtrip_and_configuration_binding() -> None:
    price = snapshot()
    raw = json.loads(price.canonical_json())
    raw["short_context"]["cached_input"] = "0.20000"
    envelope = PricingInput.from_json(json.dumps(raw, indent=2))
    assert envelope.snapshot == price
    assert envelope.snapshot.content_hash == price.content_hash
    assert dict(envelope.configuration_options()) == {
        "pricing_snapshot_hash": price.content_hash,
        "pricing_snapshot_schema_version": "1",
    }
    assert PricingInput().configuration_options() == ()
    with localcontext() as context:
        context.prec = 2
        assert calculate().cost_amount_decimal == "0.000269"


def test_contracts_are_frozen_and_envelope_states_are_consistent() -> None:
    price = snapshot()
    for value, field in [
        (price, "currency"),
        (price.short_context, "input"),
        (PricingInput(), "state"),
        (USAGE, "input_tokens"),
        (calculate(), "cost_status"),
    ]:
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, "changed")
    for state in (PricingInputState.MISSING, PricingInputState.INVALID):
        with pytest.raises(ValueError):
            PricingInput(state, price)
    with pytest.raises(ValueError):
        PricingInput(PricingInputState.VALID)


@pytest.mark.parametrize(
    "changes",
    [
        {"provider_latency_ns": -1},
        {"provider_latency_ns": True},
        {"latency_scope": "wall-clock"},
        {"cost_amount_decimal": None},
        {"cost_amount_decimal": "0.0002690"},
        {"cost_unavailable_reason": Reason.PRICING_EVIDENCE_MISSING},
    ],
)
def test_invalid_telemetry_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises((ValueError, TypeError)):
        replace(calculate(), **changes)


def test_forged_amount_or_interval_rejected_by_execution_validation() -> None:
    result = calculate()
    for evidence, completed in [
        (replace(result, cost_amount_decimal="0.00"), END),
        (result, END + timedelta(microseconds=1)),
    ]:
        with pytest.raises(ValueError, match="inconsistent"):
            evidence.validate_execution(
                "openai-provider", "gpt-5.6-terra", START, completed
            )
