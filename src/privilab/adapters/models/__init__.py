"""Approved deterministic model-provider adapters."""

from privilab.adapters.models.fixture import FixtureModelProvider
from privilab.adapters.models.governed_fixture import load_governed_fixture

__all__ = ["FixtureModelProvider", "load_governed_fixture"]
