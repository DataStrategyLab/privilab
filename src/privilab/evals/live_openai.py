"""Explicit local DSL-116 smoke execution; never imported for side effects."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from privilab.adapters.retrieval import SQLiteFtsRetrievalProvider
from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.application import (
    RunProvenance,
    RunService,
    RunStatus,
    parse_permission_policy,
)
from privilab.application.run_review import RunReviewService
from privilab.application.telemetry import PricingInput, PricingInputState
from privilab.domain import (
    ChunkId,
    RetrievalChunk,
    RetrievalSource,
    SourceEntitlement,
    SourceId,
    SyntheticRequestContext,
)
from privilab.evals import GateStatus

CASE_ID = "dsl-116-synthetic-smoke"
CASE_VERSION = "1"
_ROOT = Path(__file__).resolve().parents[3]
_CONTEXT_HASH = "e2ff7417d2960f9a3abb18cb93949b609bd3797043af93e80aebc6dede821182"
_SOURCE_HASH = "97916445e8bc983bc9945e864a88b303d2f8e7b32dc1e1ef973c598141b0c4a1"
_CONTEXT = {
    "user_id": "synthetic-user-001",
    "role_id": "synthetic-researcher",
    "client_id": "synthetic-client-001",
    "matter_id": "synthetic-matter-001",
    "workflow_id": "synthetic-workflow-001",
}


def load_pricing(path: str | None) -> PricingInput:
    """Discard unreadable/malformed content; never abort generation for pricing."""
    if path is None:
        return PricingInput()
    try:
        # Bounded reads also turn oversized files into INVALID evidence.
        with Path(path).open("r", encoding="utf-8") as handle:
            payload = handle.read(65537)
    except FileNotFoundError:
        return PricingInput()
    except (OSError, UnicodeError, ValueError):
        return PricingInput(PricingInputState.INVALID)
    return PricingInput.from_json(payload)


def _registered_fixture(
    root: Path,
    category: str,
    name: str,
    identity: str,
    digest: str,
    license_ref: str,
) -> str:
    relative = f"fixtures/{category}/{name}"
    manifest = json.loads(
        (root / "fixtures" / category / "manifest.json").read_text(encoding="utf-8")
    )
    records = manifest["records" if category == "corpus" else "fixtures"]
    matches = [record for record in records if record["id"] == identity]
    if manifest["schema_version"] != "1" or len(matches) != 1:
        raise ValueError("live fixture registration is invalid")
    record = matches[0]
    if (
        record["path"],
        record["version"],
        record["content_hash"],
        record["license_ref"],
        record["synthetic"],
    ) != (
        relative,
        "1.0.0",
        "sha256:" + digest,
        license_ref,
        True,
    ):
        raise ValueError("live fixture registration does not match the approved case")
    payload = (root / relative).read_bytes()
    if hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError("live fixture content does not match the approved case")
    return payload.decode("utf-8", errors="strict")


@dataclass(frozen=True, slots=True)
class LiveEvidence:
    run: RunProvenance
    database_path: Path
    passed: bool

    def summary(self) -> dict[str, Any]:
        run = self.run
        configuration = run.configuration
        telemetry = run.model_telemetry
        snapshot = None if telemetry is None else telemetry.pricing_snapshot
        return {
            "run_id": run.run_id.value,
            "status": run.status.value,
            "provider_id": configuration.provider_id,
            "provider_version": configuration.provider_version,
            "model_id": configuration.model_id,
            "model_version": configuration.model_version,
            "usage": None
            if telemetry is None or telemetry.usage is None
            else asdict(telemetry.usage),
            "provider_latency_ns": None
            if telemetry is None
            else telemetry.provider_latency_ns,
            "latency_scope": None if telemetry is None else telemetry.latency_scope,
            "cost_status": None if telemetry is None else telemetry.cost_status.value,
            "cost_amount_decimal": None
            if telemetry is None
            else telemetry.cost_amount_decimal,
            "cost_unavailable_reason": None
            if telemetry is None
            else telemetry.cost_unavailable_reason,
            "pricing_source_id": None if snapshot is None else snapshot.source_id,
            "pricing_snapshot_hash": None
            if snapshot is None
            else snapshot.content_hash,
            "pricing_snapshot_schema_version": None
            if snapshot is None
            else snapshot.schema_version,
            "configuration_id": configuration.configuration_id,
            "configuration_version": configuration.configuration_version,
            "configuration_hash": run.configuration_hash,
            "database_path": str(self.database_path),
        }


def run_live(repository_root: Path = _ROOT) -> LiveEvidence:
    """Compose and execute exactly one governed run after the explicit live gate."""
    if os.environ.get("PRIVILAB_LIVE_EVAL") != "1":
        raise ValueError("live evaluation requires PRIVILAB_LIVE_EVAL=1")
    context = SyntheticRequestContext.from_json(
        _registered_fixture(
            repository_root,
            "contexts",
            "synthetic_request_context_v1.json",
            "context.synthetic-request.001",
            _CONTEXT_HASH,
            "fixture:synthetic-contexts",
        )
    )
    document = json.loads(
        _registered_fixture(
            repository_root,
            "corpus",
            "synthetic_trade_notice_v1.json",
            "corpus.synthetic-trade-notice.001",
            _SOURCE_HASH,
            "fixture:synthetic-corpus",
        )
    )
    pricing = load_pricing(os.environ.get("PRIVILAB_PRICING_EVIDENCE_FILE"))
    policy = parse_permission_policy(
        {
            "schema_version": 1,
            "policy_id": "policy.dsl-116-smoke",
            "policy_version": "1",
            "synthetic": True,
            "required_context": list(_CONTEXT),
            "rules": [
                {
                    "rule_id": "synthetic-research",
                    "effect": "ALLOW",
                    "match": _CONTEXT,
                    "condition_ids": [],
                }
            ],
        }
    )
    database = repository_root / ".local" / "live-eval" / "provenance.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    with (
        closing(SQLiteFtsRetrievalProvider(":memory:")) as retrieval,
        closing(SQLiteProvenanceStore(database)) as store,
    ):
        source_id = SourceId("synthetic-trade-notice-001")
        retrieval.index_source(
            RetrievalSource(
                source_id=source_id,
                title=document["title"],
                source_version="1.0.0",
                chunks=(
                    RetrievalChunk(
                        ChunkId("synthetic-trade-notice-chunk-001"),
                        source_id,
                        0,
                        document["text"],
                    ),
                ),
                entitlements=(SourceEntitlement(source_id=source_id, **_CONTEXT),),
            )
        )
        service = RunService.from_openai(
            policy=policy,
            retrieval_provider=retrieval,
            provenance_store=store,
            configuration_id=CASE_ID,
            configuration_version=CASE_VERSION,
            retrieval_provider_id="sqlite-fts5",
            retrieval_provider_version="1",
            retrieval_limit=1,
            pricing=pricing,
            live_case_id=CASE_ID,
            live_case_version=CASE_VERSION,
        )
        outcome, view = RunReviewService(store, store).execute(
            service,
            context=context,
            task_text=(
                "Briefly summarize the supplied synthetic notice, citing its source "
                "and chunk. Do not infer legal conclusions."
            ),
            query="synthetic notice",
        )
        restored = store.get(outcome.run_id)
        if restored is None or restored != view.run or restored.model_telemetry is None:
            raise ValueError("live evidence reconstruction failed")
        passed = (
            outcome.status is RunStatus.GENERATED
            and view.evaluation is not None
            and view.evaluation.gate_status is GateStatus.PASS
            and view.review is None
        )
        return LiveEvidence(restored, database, passed)


def main() -> None:
    if os.environ.get("PRIVILAB_LIVE_EVAL") != "1":
        raise SystemExit("live evaluation requires PRIVILAB_LIVE_EVAL=1")
    try:
        evidence = run_live()
        print(json.dumps(evidence.summary(), sort_keys=True, allow_nan=False))
    except Exception:
        raise SystemExit(
            "live smoke failed; use a fresh local evidence database "
            "and validated fixtures"
        ) from None
    if not evidence.passed:
        # Only inspect availability after the governed model stage has executed.
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            raise SystemExit("live smoke validation pending approved local execution")
        raise SystemExit(
            "live smoke validation failed; inspect local metadata evidence"
        )


if __name__ == "__main__":
    main()
