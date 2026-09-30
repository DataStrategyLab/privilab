"""Immutable execution evidence and the bounded DSL-116 pricing calculation.

Pricing is operator configuration, never provider-reported billing verification.
This module has no provider, filesystem, credential, or network dependencies.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Context, Decimal, localcontext
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

LATENCY_SCOPE = "provider-execution-inclusive-of-retries-v1"
CALCULATION_RULE = "openai-gpt56-text-v1"
UNIT_BASIS = "per_1000000_tokens"
MAX_INTEGER = 2**63 - 1
TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
)
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_PRICING_SOURCE_HOSTS = frozenset(
    {"openai.com", "developers.openai.com", "platform.openai.com"}
)
_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z"
)


class CostStatus(StrEnum):
    CALCULATED = "CALCULATED"
    NOT_CALCULATED = "NOT_CALCULATED"


class CostUnavailableReason(StrEnum):
    PRICING_EVIDENCE_MISSING = "PRICING_EVIDENCE_MISSING"
    PRICING_EVIDENCE_INVALID = "PRICING_EVIDENCE_INVALID"
    BILLING_MODE_UNCONFIRMED = "BILLING_MODE_UNCONFIRMED"
    PRICING_EVIDENCE_NOT_APPLICABLE = "PRICING_EVIDENCE_NOT_APPLICABLE"
    PRICING_RULE_UNSUPPORTED = "PRICING_RULE_UNSUPPORTED"
    USAGE_EVIDENCE_INSUFFICIENT = "USAGE_EVIDENCE_INSUFFICIENT"
    USAGE_EVIDENCE_INCONSISTENT = "USAGE_EVIDENCE_INCONSISTENT"


class PricingInputState(StrEnum):
    MISSING = "MISSING"
    INVALID = "INVALID"
    VALID = "VALID"


class ProcessingMode(StrEnum):
    STANDARD = "standard"
    UNCONFIRMED = "unconfirmed"
    UNKNOWN = "unknown"
    FLEX = "flex"
    BATCH = "batch"
    FAST = "fast"
    PRIORITY = "priority"
    ULTRAFAST = "ultrafast"
    UNSUPPORTED = "unsupported"


class BillingMode(StrEnum):
    STANDARD_SYNCHRONOUS = "STANDARD_SYNCHRONOUS"
    UNCONFIRMED = "UNCONFIRMED"
    UNKNOWN = "UNKNOWN"
    FLEX = "FLEX"
    BATCH = "BATCH"
    FAST = "FAST"
    PRIORITY = "PRIORITY"
    ULTRAFAST = "ULTRAFAST"
    UNSUPPORTED = "UNSUPPORTED"


def nonnegative_integer(value: object) -> None:
    if type(value) is not int or not 0 <= value <= MAX_INTEGER:
        raise ValueError("evidence count must fit a non-negative SQLite integer")


def canonical_decimal(value: str) -> str:
    """Normalize fixed-point evidence without binary floats or rounding."""
    if not isinstance(value, str) or len(value) > 320 or not _DECIMAL.fullmatch(value):
        raise ValueError("monetary evidence must be a non-negative decimal string")
    whole, _, fraction = value.partition(".")
    return whole + "." + fraction.rstrip("0").ljust(2, "0")


def utc_timestamp(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("pricing timestamps must be timezone-aware")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError):
        raise ValueError(
            "pricing timestamp is outside the supported UTC range"
        ) from None


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise ValueError("pricing timestamp must be RFC3339")
    return utc_timestamp(datetime.fromisoformat(value))


def _identifier(value: object) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError("pricing identifier is invalid")


def _approved_pricing_source(value: object) -> bool:
    """Check the DSL-116 origin allowlist without DNS or network access."""
    if (
        not isinstance(value, str)
        or len(value) > 2048
        or any(ord(c) <= 32 or ord(c) >= 127 for c in value)
    ):
        return False
    try:
        url = urlsplit(value)
        hostname = (url.hostname or "").lower()
        port = url.port  # Access validates malformed and out-of-range ports.
    except ValueError:
        # Discard parser errors, which may contain operator-supplied content.
        return False
    return (
        url.scheme == "https"
        and hostname in _PRICING_SOURCE_HOSTS
        and port in (None, 443)
        and url.username is None
        and url.password is None
        # Require an omitted port or canonical :443, including exact authority.
        and url.netloc.lower() in (hostname, f"{hostname}:443")
        and "?" not in value
        and "#" not in value
    )


def _object(
    value: object, required: set[str], optional: set[str] | frozenset[str] = frozenset()
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or not required <= value.keys() <= required | optional
    ):
        raise ValueError("pricing fields do not match the schema")
    return value


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate pricing field")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class TokenRates:
    input: str
    cached_input: str
    cache_write: str
    output: str

    def __post_init__(self) -> None:
        for name in ("input", "cached_input", "cache_write", "output"):
            rate = canonical_decimal(getattr(self, name))
            if len(rate) > 128:
                raise ValueError("pricing rate exceeds supported precision")
            object.__setattr__(self, name, rate)


@dataclass(frozen=True, slots=True)
class BillingAttestation:
    billing_mode_attestation: BillingMode
    attested_by: str
    attestation_version: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.billing_mode_attestation, BillingMode)
            or self.attested_by != "operator"
            or self.attestation_version != "1"
        ):
            raise ValueError("unsupported billing attestation structure")


@dataclass(frozen=True, slots=True)
class PricingSnapshot:
    schema_version: str
    provider_id: str
    model_id: str
    processing_mode: ProcessingMode
    source_id: str
    source_url: str
    retrieved_at: datetime
    effective_at: datetime | None
    expires_at: datetime
    currency: str
    unit_basis: str
    context_threshold_input_tokens: int
    short_context: TokenRates
    long_context: TokenRates
    calculation_rule_version: str
    billing_attestation: BillingAttestation | None = None

    def __post_init__(self) -> None:
        if self.schema_version != "1":
            raise ValueError("unsupported pricing schema")
        for name in (
            "provider_id",
            "model_id",
            "source_id",
            "unit_basis",
            "calculation_rule_version",
        ):
            _identifier(getattr(self, name))
        if not isinstance(self.processing_mode, ProcessingMode):
            raise TypeError("processing_mode must be a bounded ProcessingMode")
        if not isinstance(self.currency, str) or not re.fullmatch(
            r"[A-Z]{3}", self.currency
        ):
            raise ValueError("currency must be a three-letter currency code")
        if not _approved_pricing_source(self.source_url):
            raise ValueError("pricing source must be an approved public HTTPS URL")
        for name in ("retrieved_at", "expires_at"):
            object.__setattr__(self, name, utc_timestamp(getattr(self, name)))
        if self.effective_at is not None:
            object.__setattr__(self, "effective_at", utc_timestamp(self.effective_at))
        nonnegative_integer(self.context_threshold_input_tokens)
        if not isinstance(self.short_context, TokenRates) or not isinstance(
            self.long_context, TokenRates
        ):
            raise TypeError("pricing tables must be immutable TokenRates")
        if self.billing_attestation is not None and not isinstance(
            self.billing_attestation, BillingAttestation
        ):
            raise TypeError("billing_attestation must be immutable or absent")

    def canonical_json(self) -> str:
        value = asdict(self)
        for name in ("retrieved_at", "effective_at", "expires_at"):
            stamp = getattr(self, name)
            value[name] = (
                None if stamp is None else stamp.isoformat(timespec="microseconds")
            )
        if self.billing_attestation is None:
            del value["billing_attestation"]
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

    @property
    def content_hash(self) -> str:
        return (
            "sha256:"
            + hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
        )

    @classmethod
    def from_json(cls, payload: str) -> PricingSnapshot:
        if not isinstance(payload, str) or len(payload) > 65536:
            raise ValueError("pricing evidence must be bounded JSON text")
        value = _object(
            json.loads(payload, object_pairs_hook=_unique_pairs),
            {
                "schema_version",
                "provider_id",
                "model_id",
                "processing_mode",
                "source_id",
                "source_url",
                "retrieved_at",
                "effective_at",
                "expires_at",
                "currency",
                "unit_basis",
                "context_threshold_input_tokens",
                "short_context",
                "long_context",
                "calculation_rule_version",
            },
            {"billing_attestation"},
        )
        for name in ("short_context", "long_context"):
            value[name] = TokenRates(
                **_object(
                    value[name], {"input", "cached_input", "cache_write", "output"}
                )
            )
        value["processing_mode"] = ProcessingMode(value["processing_mode"])
        for name in ("retrieved_at", "expires_at"):
            value[name] = _parse_timestamp(value[name])
        if value["effective_at"] is not None:
            value["effective_at"] = _parse_timestamp(value["effective_at"])
        if "billing_attestation" in value:
            attestation = _object(
                value["billing_attestation"],
                {"billing_mode_attestation", "attested_by", "attestation_version"},
            )
            value["billing_attestation"] = BillingAttestation(
                BillingMode(attestation["billing_mode_attestation"]),
                attestation["attested_by"],
                attestation["attestation_version"],
            )
        return cls(**value)


@dataclass(frozen=True, slots=True)
class PricingInput:
    """Only a VALID envelope may retain operator-supplied evidence."""

    state: PricingInputState = PricingInputState.MISSING
    snapshot: PricingSnapshot | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, PricingInputState):
            raise TypeError("pricing input state must be bounded")
        if self.state is PricingInputState.VALID:
            if not isinstance(self.snapshot, PricingSnapshot):
                raise ValueError("VALID pricing requires a snapshot")
        elif self.snapshot is not None:
            raise ValueError("unavailable pricing must not retain input content")

    @classmethod
    def from_json(cls, payload: str) -> PricingInput:
        try:
            snapshot = PricingSnapshot.from_json(payload)
        except (TypeError, ValueError, OverflowError, RecursionError):
            return cls(PricingInputState.INVALID)
        return cls(PricingInputState.VALID, snapshot)

    def configuration_options(self) -> tuple[tuple[str, str], ...]:
        if self.snapshot is None:
            return ()
        return (
            ("pricing_snapshot_hash", self.snapshot.content_hash),
            ("pricing_snapshot_schema_version", self.snapshot.schema_version),
        )


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None

    def __post_init__(self) -> None:
        for name in TOKEN_FIELDS:
            value = getattr(self, name)
            if value is not None:
                nonnegative_integer(value)


@dataclass(frozen=True, slots=True)
class ModelTelemetry:
    provider_latency_ns: int
    latency_scope: str
    usage: ModelUsage | None
    cost_status: CostStatus
    cost_amount_decimal: str | None
    cost_unavailable_reason: CostUnavailableReason | None
    pricing_snapshot: PricingSnapshot | None

    def __post_init__(self) -> None:
        nonnegative_integer(self.provider_latency_ns)
        if self.latency_scope != LATENCY_SCOPE:
            raise ValueError("unsupported latency scope")
        if self.usage is not None and not isinstance(self.usage, ModelUsage):
            raise TypeError("usage must be application-owned evidence")
        if not isinstance(self.cost_status, CostStatus):
            raise TypeError("cost status must be bounded")
        if self.pricing_snapshot is not None and not isinstance(
            self.pricing_snapshot, PricingSnapshot
        ):
            raise TypeError("pricing snapshot must be validated immutable evidence")
        if self.cost_status is CostStatus.CALCULATED:
            if (
                self.cost_amount_decimal is None
                or self.cost_unavailable_reason is not None
                or self.pricing_snapshot is None
                or self.usage is None
            ):
                raise ValueError(
                    "calculated cost requires usage, pricing, and an amount"
                )
            if canonical_decimal(self.cost_amount_decimal) != self.cost_amount_decimal:
                raise ValueError("cost amount must be canonical")
        elif self.cost_amount_decimal is not None or not isinstance(
            self.cost_unavailable_reason, CostUnavailableReason
        ):
            raise ValueError("unavailable cost requires only a bounded reason")

    def validate_execution(
        self,
        provider_id: str,
        model_id: str,
        started_at: datetime,
        completed_at: datetime,
    ) -> None:
        """Reject cost evidence inconsistent with the exact persisted run."""
        state = (
            PricingInputState.VALID
            if self.pricing_snapshot is not None
            else (
                PricingInputState.INVALID
                if self.cost_unavailable_reason
                is CostUnavailableReason.PRICING_EVIDENCE_INVALID
                else PricingInputState.MISSING
            )
        )
        expected = build_telemetry(
            self.usage,
            self.provider_latency_ns,
            PricingInput(state, self.pricing_snapshot),
            provider_id=provider_id,
            model_id=model_id,
            started_at=started_at,
            completed_at=completed_at,
        )
        if self != expected:
            raise ValueError("telemetry is inconsistent with execution evidence")


def build_telemetry(
    usage: ModelUsage | None,
    latency_ns: int,
    pricing: PricingInput,
    *,
    provider_id: str,
    model_id: str,
    started_at: datetime,
    completed_at: datetime,
) -> ModelTelemetry:
    """Apply deterministic precedence; never fabricate missing evidence."""
    started_at, completed_at = utc_timestamp(started_at), utc_timestamp(completed_at)
    if completed_at < started_at:
        raise ValueError("completion must not precede start")
    if not isinstance(pricing, PricingInput):
        raise TypeError("pricing must be an immutable PricingInput")
    if usage is not None and not isinstance(usage, ModelUsage):
        raise TypeError("usage must be application-owned evidence")
    snapshot = pricing.snapshot
    reason: CostUnavailableReason | None = None
    amount: str | None = None
    if pricing.state is PricingInputState.MISSING:
        reason = CostUnavailableReason.PRICING_EVIDENCE_MISSING
    elif pricing.state is PricingInputState.INVALID:
        reason = CostUnavailableReason.PRICING_EVIDENCE_INVALID
    else:
        assert snapshot is not None
        attestation = snapshot.billing_attestation
        if (
            snapshot.processing_mode is not ProcessingMode.STANDARD
            or attestation is None
            or attestation.billing_mode_attestation
            is not BillingMode.STANDARD_SYNCHRONOUS
        ):
            reason = CostUnavailableReason.BILLING_MODE_UNCONFIRMED
        elif (
            (provider_id, model_id) != ("openai-provider", "gpt-5.6-terra")
            or (snapshot.provider_id, snapshot.model_id) != (provider_id, model_id)
            or snapshot.retrieved_at > started_at
            or (
                snapshot.effective_at is not None and snapshot.effective_at > started_at
            )
            or completed_at > snapshot.expires_at
        ):
            reason = CostUnavailableReason.PRICING_EVIDENCE_NOT_APPLICABLE
        elif (
            snapshot.calculation_rule_version != CALCULATION_RULE
            or snapshot.unit_basis != UNIT_BASIS
        ):
            reason = CostUnavailableReason.PRICING_RULE_UNSUPPORTED
        elif (
            usage is None
            or usage.input_tokens is None
            or usage.cached_input_tokens is None
            or usage.cache_write_tokens is None
            or usage.output_tokens is None
        ):
            reason = CostUnavailableReason.USAGE_EVIDENCE_INSUFFICIENT
        elif (
            usage.cached_input_tokens + usage.cache_write_tokens > usage.input_tokens
            or (
                usage.total_tokens is not None
                and usage.total_tokens != usage.input_tokens + usage.output_tokens
            )
            or (
                usage.reasoning_tokens is not None
                and usage.reasoning_tokens > usage.output_tokens
            )
        ):
            reason = CostUnavailableReason.USAGE_EVIDENCE_INCONSISTENT
        else:
            rates = (
                snapshot.long_context
                if usage.input_tokens > snapshot.context_threshold_input_tokens
                else snapshot.short_context
            )
            # Rates have at most 128 characters and counts at most 19 digits.
            # This precision preserves every product, sum and division by 10**6.
            with localcontext(Context(prec=320)):
                ordinary = (
                    usage.input_tokens
                    - usage.cached_input_tokens
                    - usage.cache_write_tokens
                )
                cost = (
                    ordinary * Decimal(rates.input)
                    + usage.cached_input_tokens * Decimal(rates.cached_input)
                    + usage.cache_write_tokens * Decimal(rates.cache_write)
                    + usage.output_tokens * Decimal(rates.output)
                ) / Decimal(1_000_000)
                # Calculated values may be wider than one individual rate.
                whole, _, fraction = format(cost, "f").partition(".")
                amount = whole + "." + fraction.rstrip("0").ljust(2, "0")
    return ModelTelemetry(
        latency_ns,
        LATENCY_SCOPE,
        usage,
        CostStatus.CALCULATED if reason is None else CostStatus.NOT_CALCULATED,
        amount,
        reason,
        snapshot,
    )
