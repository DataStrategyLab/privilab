from pathlib import Path

import pytest

from privilab.adapters.models import FixtureModelProvider
from privilab.application.model_provider import (
    ModelProvider,
    ModelRequest,
    ModelSourceChunk,
)
from privilab.domain.research import ResearchResult

ROOT = Path(__file__).parents[2]
MODEL_OUTPUTS = ROOT / "src/privilab/adapters/models/resources/governed_fixtures"


def exercise_provider_contract(
    provider: ModelProvider,
    request: ModelRequest,
) -> ResearchResult:
    """Make structural conformance part of the strict-mypy test contract."""
    return provider.generate(request)


def test_fixture_provider_conforms_to_model_provider_contract() -> None:
    provider = FixtureModelProvider(
        (MODEL_OUTPUTS / "synthetic_happy_path_v1.json").read_text(encoding="utf-8")
    )
    request = ModelRequest(
        task_text="Summarize the supplied synthetic source chunks.",
        source_chunks=(
            ModelSourceChunk(
                "synthetic-source-001",
                "synthetic-chunk-001",
                "First caller-supplied synthetic source chunk.",
            ),
            ModelSourceChunk(
                "synthetic-source-002",
                "synthetic-chunk-002",
                "Second caller-supplied synthetic source chunk.",
            ),
        ),
    )

    result = exercise_provider_contract(provider, request)

    assert isinstance(result, ResearchResult)
    assert result.answer_text


def test_openai_provider_preserves_the_provider_neutral_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from privilab.adapters.models.openai import (
        OpenAIGeneration,
        OpenAIProvider,
        OpenAIUsage,
    )

    expected = ResearchResult("Synthetic contract result.")
    generation = OpenAIGeneration(expected, OpenAIUsage(input_tokens=5))

    def fake_execution(self: OpenAIProvider, request: ModelRequest) -> OpenAIGeneration:
        return generation

    monkeypatch.setattr(OpenAIProvider, "generate_with_usage", fake_execution)
    provider: ModelProvider = OpenAIProvider()
    assert (
        exercise_provider_contract(provider, ModelRequest("Synthetic task.", ()))
        is expected
    )
