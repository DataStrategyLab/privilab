"""Executable, local synthetic smoke evaluation for the DSL-113 gate."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import cast

from privilab.application import (
    ChunkProvenance,
    ContextProvenance,
    PermissionProvenance,
    PermissionStopReason,
    RunConfiguration,
    RunId,
    RunOutcome,
    RunProvenance,
    RunStatus,
    SourceProvenance,
)
from privilab.domain import (
    CitationReference,
    PermissionResult,
    PermissionState,
    ResearchResult,
)
from privilab.evals import evaluators
from privilab.evals.contracts import (
    CriterionStatus,
    EvaluationEvidence,
    EvaluationInput,
    EvaluatorKind,
    GateStatus,
    TaskDefinition,
)
from privilab.evals.runner import evaluate

_ROOT = Path(__file__).parents[3]
_SMOKE_DIRECTORY = _ROOT / "evals" / "smoke"


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate smoke field {key!r}")
        value[key] = item
    return value


@dataclass(frozen=True, slots=True)
class SmokeCase:
    case_id: str
    case_version: str
    scenario: str
    expected_gate: GateStatus
    expected_criteria: tuple[tuple[str, CriterionStatus], ...]

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.case_id, "case_id"),
            (self.case_version, "case_version"),
            (self.scenario, "scenario"),
        ):
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{field_name} must be a non-empty, trimmed string")
        if self.scenario not in {
            "valid-generated",
            "nonexistent-chunk",
            "source-outside-run-context",
            "permission-stopped",
            "evaluator-execution-error",
        }:
            raise ValueError("unsupported smoke scenario")
        if not isinstance(self.expected_gate, GateStatus):
            raise TypeError("expected_gate must be GateStatus")
        if tuple(sorted(self.expected_criteria)) != self.expected_criteria:
            raise ValueError("expected_criteria must be sorted")


def _load_smoke_cases(path: Path) -> tuple[SmokeCase, ...]:
    decoded = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_object_without_duplicates
    )
    if not isinstance(decoded, dict) or set(decoded) != {
        "schema_version",
        "synthetic",
        "cases",
    }:
        raise ValueError("smoke cases fields do not match the contract")
    if decoded["schema_version"] != "1" or decoded["synthetic"] is not True:
        raise ValueError("smoke cases must be versioned synthetic data")
    raw_cases = decoded["cases"]
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("smoke cases must be a non-empty array")
    cases: list[SmokeCase] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict) or set(raw_case) != {
            "case_id",
            "case_version",
            "scenario",
            "expected_gate",
            "expected_criteria",
        }:
            raise ValueError("smoke case fields do not match the contract")
        expected_criteria = raw_case["expected_criteria"]
        if not isinstance(expected_criteria, dict):
            raise ValueError("expected_criteria must be an object")
        try:
            cases.append(
                SmokeCase(
                    case_id=cast(str, raw_case["case_id"]),
                    case_version=cast(str, raw_case["case_version"]),
                    scenario=cast(str, raw_case["scenario"]),
                    expected_gate=GateStatus(raw_case["expected_gate"]),
                    expected_criteria=tuple(
                        sorted(
                            (
                                criterion_id,
                                CriterionStatus(expected_status),
                            )
                            for criterion_id, expected_status in (
                                expected_criteria.items()
                            )
                        )
                    ),
                )
            )
        except (TypeError, ValueError) as error:
            raise ValueError("smoke case contains an invalid value") from error
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("smoke case IDs must be unique")
    return tuple(cases)


def _configuration() -> RunConfiguration:
    return RunConfiguration(
        configuration_id="synthetic-evaluation-smoke",
        configuration_version="1.0.0",
        provider_id="fixture-model-provider",
        provider_version="1",
        model_id="synthetic-model",
        model_version="1.0.0",
        retrieval_provider_id="synthetic-retrieval",
        retrieval_provider_version="1",
    )


def _generated_input(citation: CitationReference) -> EvaluationInput:
    stamp = datetime(2026, 9, 20, tzinfo=UTC)
    run_id = RunId("synthetic-evaluation-generated")
    provenance = RunProvenance(
        run_id=run_id,
        started_at=stamp,
        completed_at=stamp,
        status=RunStatus.GENERATED,
        context=ContextProvenance(None, None, None, None, None),
        configuration=_configuration(),
        configuration_hash=f"sha256:{sha256(b'synthetic-evaluation').hexdigest()}",
        permission=PermissionProvenance(
            "synthetic-policy", "1.0.0", 1, PermissionState.ALLOW
        ),
        retrieval_called=True,
        model_called=True,
        sources=(
            SourceProvenance(
                "synthetic-source",
                "1.0.0",
                (ChunkProvenance("synthetic-chunk", 0, 0),),
            ),
        ),
    )
    return EvaluationInput(
        outcome=RunOutcome(
            run_id,
            RunStatus.GENERATED,
            PermissionResult(PermissionState.ALLOW),
            ResearchResult("Synthetic answer.", (citation,)),
        ),
        provenance=provenance,
    )


def _stopped_input() -> EvaluationInput:
    stamp = datetime(2026, 9, 20, tzinfo=UTC)
    run_id = RunId("synthetic-evaluation-stopped")
    return EvaluationInput(
        outcome=RunOutcome(
            run_id,
            RunStatus.PERMISSION_STOPPED,
            PermissionResult(PermissionState.BLOCK),
        ),
        provenance=RunProvenance(
            run_id=run_id,
            started_at=stamp,
            completed_at=stamp,
            status=RunStatus.PERMISSION_STOPPED,
            context=ContextProvenance(None, None, None, None, None),
            configuration=_configuration(),
            configuration_hash=f"sha256:{sha256(b'synthetic-evaluation-stopped').hexdigest()}",
            permission=PermissionProvenance(
                "synthetic-policy", "1.0.0", 1, PermissionState.BLOCK
            ),
            retrieval_called=False,
            model_called=False,
            stop_reason=PermissionStopReason.BLOCK,
        ),
    )


def _input_for(case: SmokeCase) -> EvaluationInput:
    if case.scenario == "permission-stopped":
        return _stopped_input()
    citation = {
        "valid-generated": CitationReference("synthetic-source", "synthetic-chunk"),
        "nonexistent-chunk": CitationReference("synthetic-source", "missing-chunk"),
        "source-outside-run-context": CitationReference(
            "outside-source", "synthetic-chunk"
        ),
        "evaluator-execution-error": CitationReference(
            "synthetic-source", "synthetic-chunk"
        ),
    }[case.scenario]
    return _generated_input(citation)


@contextmanager
def _controlled_evaluator_error(enabled: bool) -> Iterator[None]:
    if not enabled:
        yield
        return

    def raise_for_smoke(
        _: EvaluationInput, __: evaluators.ProvenanceIndex
    ) -> tuple[CriterionStatus, EvaluationEvidence]:
        raise RuntimeError("synthetic evaluator execution failure")

    original = evaluators.EVALUATOR_REGISTRY
    replacement = dict(original)
    replacement[EvaluatorKind.AUTHORIZED_SOURCE] = raise_for_smoke
    evaluators.EVALUATOR_REGISTRY = MappingProxyType(replacement)
    try:
        yield
    finally:
        evaluators.EVALUATOR_REGISTRY = original


def run_smoke() -> tuple[tuple[str, bool], ...]:
    """Run every declared scenario against independent fixed expectations."""
    task = TaskDefinition.from_json(
        (_SMOKE_DIRECTORY / "rubric.json").read_text(encoding="utf-8")
    )
    outcomes: list[tuple[str, bool]] = []
    for case in _load_smoke_cases(_SMOKE_DIRECTORY / "cases.json"):
        with _controlled_evaluator_error(case.scenario == "evaluator-execution-error"):
            result = evaluate(_input_for(case), task)
        actual_criteria = tuple(
            sorted((item.criterion_id, item.status) for item in result.criteria)
        )
        outcomes.append(
            (
                case.case_id,
                result.gate.status is case.expected_gate
                and actual_criteria == case.expected_criteria,
            )
        )
    return tuple(outcomes)


def main() -> None:
    outcomes = run_smoke()
    if not outcomes or not all(matched for _case_id, matched in outcomes):
        raise SystemExit("offline smoke evaluation failed")
    print(f"PASS: {len(outcomes)} deterministic offline smoke cases matched")


if __name__ == "__main__":
    main()
