"""Deterministic fixture implementation of the model-provider port."""

from __future__ import annotations

from dataclasses import dataclass

from privilab.application.model_provider import (
    MalformedModelOutputError,
    ModelRequest,
)
from privilab.domain.research import ResearchResult


@dataclass(frozen=True, slots=True)
class FixtureModelProvider:
    """Parse an injected fixture payload without external access or hidden state."""

    output_json: str

    def __post_init__(self) -> None:
        if not isinstance(self.output_json, str):
            raise TypeError("output_json must be a string")

    def generate(self, request: ModelRequest) -> ResearchResult:
        """Return the configured result or expose its deterministic parse failure."""
        if not isinstance(request, ModelRequest):
            raise TypeError("request must be a ModelRequest")
        try:
            return ResearchResult.from_json(self.output_json)
        except (TypeError, ValueError) as error:
            raise MalformedModelOutputError(
                "model output does not satisfy the research-result contract"
            ) from error


__all__ = ["FixtureModelProvider"]
