# DSL-116 local live smoke

`make eval-live` explicitly opts into one controlled local OpenAI execution.
It is outside `make ci`, `ci-stages`, tests, deterministic smoke/golden evaluation,
and package building. The GitHub live-eval workflow remains disabled.

Run the command from the repository root after deterministic verification:

```sh
make ci
git diff --check
make eval-live
```

The Make target sets `PRIVILAB_LIVE_EVAL=1`. Direct module execution refuses to
proceed without that exact value. `OPENAI_API_KEY` must already be available in
the approved local environment; it is read at the governed model stage, never
at import. Do not put credentials in repository files, pricing evidence, or chat.
Without credentials, the attempt records a model-stage failure and reports
`live smoke validation pending approved local execution`.

The versioned `dsl-116-synthetic-smoke` case reuses the registered, licensed
synthetic request context and synthetic trade notice, checking their pinned
identities and content hashes. It does not load the DSL-117 task pack. The runner
uses permission evaluation, application-created AccessScope, in-memory SQLite/FTS
authorization filtering, `RunService.from_openai`, and existing downstream
evaluation. No human decision is created. A passing smoke is not release approval.

## Pricing input

Optionally set `PRIVILAB_PRICING_EVIDENCE_FILE` to an operator-maintained local,
untracked JSON file. No vendor prices or expiry dates are supplied by the code.
The file is read once; no vendor URL is fetched. Input is converted to an immutable
application envelope: `MISSING`, `INVALID`, or `VALID(snapshot)`.

Absent input or a missing file becomes `MISSING`. Present unreadable, invalid
UTF-8, oversized (over 65,536 characters), malformed JSON, or schema-invalid input
becomes `INVALID`. Both allow the governed run to continue. Neither retains file
content, path, or exception in provenance. Duplicate/unknown JSON keys fail
validation. Missing required fields are not inferred.

The strict snapshot schema is:

| Field | Representation |
| --- | --- |
| `schema_version` | `"1"` |
| `provider_id`, `model_id` | Identifiers; calculation requires `openai-provider` and `gpt-5.6-terra` |
| `processing_mode` | Enum described below |
| `source_id`, `source_url` | Pricing-source identity and approved public-origin HTTPS URL as restricted below |
| `retrieved_at`, `expires_at` | Required aware RFC3339 timestamps |
| `effective_at` | Aware RFC3339 timestamp or explicit JSON null |
| `currency` | Three uppercase letters; no currency conversion |
| `unit_basis` | Calculation supports `per_1000000_tokens` |
| `context_threshold_input_tokens` | Non-negative integer |
| `short_context`, `long_context` | Each contains exactly `input`, `cached_input`, `cache_write`, `output` |
| Rate values | Non-negative fixed-point decimal strings, never JSON numbers |
| `calculation_rule_version` | Calculation supports `openai-gpt56-text-v1` |
| `billing_attestation` | Optional object described below; omit if unconfirmed |

`source_url` must contain at most 2,048 ASCII characters, without whitespace or
control characters, credentials, a query, or a fragment (including empty `?` or
`#` delimiters). DSL-116 permits only the exact hostnames `openai.com`,
`developers.openai.com`, and `platform.openai.com`, compared in lowercase. The
authority must be that hostname alone or followed by the canonical HTTPS port
`:443`. Other hosts, suffix lookalikes, trailing-dot hosts, private/local/IP
authorities, and malformed or other ports are rejected. Validation performs no
DNS resolution or network lookup. A rejected URL produces `INVALID` pricing and
`NOT_CALCULATED / PRICING_EVIDENCE_INVALID` without preventing generation or
retaining the URL or parser error in provenance, configuration, or live output.

The supported attestation shape is:

```json
{
  "processing_mode": "standard",
  "billing_attestation": {
    "billing_mode_attestation": "STANDARD_SYNCHRONOUS",
    "attested_by": "operator",
    "attestation_version": "1"
  }
}
```

This is a schema fragment, not a complete pricing file. Processing-mode enums are
`standard`, `unconfirmed`, `unknown`, `flex`, `batch`, `fast`, `priority`,
`ultrafast`, and `unsupported`. Attestation-mode enums are `STANDARD_SYNCHRONOUS`,
`UNCONFIRMED`, `UNKNOWN`, `FLEX`, `BATCH`, `FAST`, `PRIORITY`, `ULTRAFAST`, and
`UNSUPPORTED`. A present attestation must contain exactly the three shown fields;
only the non-identifying role `operator` and version `"1"` are supported. A partial
object, explicit null, unknown enum, or unsupported attestation version is invalid
schema. Omission or a schema-valid unconfirmed/unsupported mode is unconfirmed
billing evidence.

The operator asserts that this snapshot applies to the processing mode used for
this controlled live run. This is configuration/evidence, not provider telemetry.
PriviLAB does not independently verify account settings, invoices, or final billed
amounts. Synchronous requests, the Responses endpoint, omitted `service_tier`,
account expectations, and standard rates never imply an attestation.

## Calculation and unavailable reasons

Pricing must match the executed provider/model. UTC-normalized validity checks
use the exact run timestamps that are persisted, with completion captured once:

```text
retrieved_at <= started_at
effective_at is null OR effective_at <= started_at
completed_at <= expires_at
```

Expiry is never extended. The explicit reason precedence is:

1. `PRICING_EVIDENCE_MISSING`: missing envelope.
2. `PRICING_EVIDENCE_INVALID`: invalid envelope.
3. `BILLING_MODE_UNCONFIRMED`: no supported standard synchronous attestation.
4. `PRICING_EVIDENCE_NOT_APPLICABLE`: identity or temporal mismatch.
5. `PRICING_RULE_UNSUPPORTED`: unsupported rule or unit basis.
6. `USAGE_EVIDENCE_INSUFFICIENT`: required billing dimensions are missing.
7. `USAGE_EVIDENCE_INCONSISTENT`: contradictory supplied counts.

The sole rule selects long-context rates when `input_tokens > threshold`, then
uses Decimal arithmetic:

```text
ordinary = input_tokens - cached_input_tokens - cache_write_tokens
cost = (ordinary * input_rate + cached_input_tokens * cached_input_rate
        + cache_write_tokens * cache_write_rate + output_tokens * output_rate)
       / 1_000_000
```

Input, output, cached-input, and cache-write counts must all be present. No count
is inferred. Cache counts cannot exceed input. If supplied, total must equal
input plus output and reasoning cannot exceed output. Total tokens are not a
calculation input; reasoning is retained but never charged separately.

`CALCULATED` has an exact canonical decimal amount and no unavailable reason.
`NOT_CALCULATED` has a SQL NULL amount and one bounded reason, never an invented
zero. A genuine computed zero remains possible. Fixed-point monetary strings
retain at least two fractional digits without rounding to cents. Counts fit
non-negative signed SQLite integers; canonical rates are limited to 128 characters.
The arithmetic uses its own sufficient decimal precision independent of caller
decimal settings. All test rates are synthetic.

## Durable evidence and reconstruction

The database is `.local/live-eval/provenance.sqlite3`. Retrieval text lives only
in the in-memory index. The durable `model_telemetry` table has one row per model
execution, with `run_id` as primary/foreign key to `model_executions`. Columns are:

- `latency_ns`, `latency_scope`;
- `usage_present`, `input_tokens`, `output_tokens`, `total_tokens`,
  `cached_input_tokens`, `cache_write_tokens`, `reasoning_tokens`;
- `cost_status`, `cost_amount_decimal`, `cost_unavailable_reason`;
- `pricing_snapshot_json`.

`usage_present` preserves absent usage versus an existing usage object whose
individual dimensions are all missing. Full valid pricing snapshots, including
attestation, live solely in telemetry provenance. Run configuration retains
existing provider settings plus stable case identity/version and the canonical
snapshot SHA-256/schema version when valid. It does not duplicate pricing fields.

Latency brackets the entire `generate_with_usage` call using `time.monotonic_ns`.
Scope is `provider-execution-inclusive-of-retries-v1`, including application retry
attempts, backoff, and server-directed delays. No actual retry count is asserted.
Failures retain elapsed latency and missing usage under existing model-failure
semantics. Neither usage for failed attempts nor their billed cost is inferred.

Telemetry is inserted in the run's atomic append transaction before finalization.
Updates, deletion, replacement, reassignment, and backfilling finalized runs are
rejected. `SQLiteProvenanceStore.get(run_id)` validates and reconstructs immutable
evidence, including consistency with the exact execution identity and timestamps.
Fixture/no-telemetry records remain valid in the new schema.

The existing fresh-schema policy remains: pre-DSL-116 databases are rejected
without repair or migration. Preserve old evidence separately and start with a
fresh local database; the command never deletes or replaces one automatically.

Output contains only permitted run/configuration/provider identities, usage,
latency, cost metadata, pricing identity/hash, and local database location. No
prompt/query/source/answer text, raw provider response, raw exception, or credential
is persisted or printed. Cost unavailability alone does not fail the smoke;
generation, existing evaluation gates, and reconstruction must succeed. Live
failures never change deterministic fixtures or expectations.

Recorded cost is an execution estimate reconstructed from reported usage and
operator-supplied pricing evidence. It is not an invoice or a future-cost
guarantee, and establishes no privacy, retention, privilege, compliance, savings,
security, or production-fitness claim.
