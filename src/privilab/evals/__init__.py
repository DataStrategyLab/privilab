"""Deterministic, metadata-only P0 evaluation and critical gating."""

from privilab.evals.contracts import (
    CriterionCriticality,
    CriterionDefinition,
    CriterionResult,
    CriterionStatus,
    CriticalGateResult,
    EvaluationEvidence,
    EvaluationInput,
    EvaluationResult,
    EvaluationRubric,
    EvaluatorKind,
    GateBlock,
    GateStatus,
    ReasonCode,
    TaskDefinition,
    p0_task_definition,
)
from privilab.evals.runner import calculate_gate, evaluate

__all__ = [
    "CriterionCriticality",
    "CriterionDefinition",
    "CriterionResult",
    "CriterionStatus",
    "CriticalGateResult",
    "EvaluationEvidence",
    "EvaluationInput",
    "EvaluationResult",
    "EvaluationRubric",
    "EvaluatorKind",
    "GateBlock",
    "GateStatus",
    "ReasonCode",
    "TaskDefinition",
    "calculate_gate",
    "evaluate",
    "p0_task_definition",
]
