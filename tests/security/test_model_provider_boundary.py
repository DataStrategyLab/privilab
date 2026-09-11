from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
APPLICATION_CONTRACT = ROOT / "src/privilab/application/model_provider.py"
FIXTURE_PROVIDER = ROOT / "src/privilab/adapters/models/fixture.py"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }


def test_model_contract_has_only_standard_library_and_domain_dependencies() -> None:
    assert imported_modules(APPLICATION_CONTRACT) == {
        "__future__",
        "dataclasses",
        "privilab.domain.research",
        "typing",
    }


def test_fixture_provider_has_only_inward_model_contract_dependencies() -> None:
    assert imported_modules(FIXTURE_PROVIDER) == {
        "__future__",
        "dataclasses",
        "privilab.application.model_provider",
        "privilab.domain.research",
    }


def test_fixture_provider_cannot_load_or_execute_external_content() -> None:
    tree = ast.parse(FIXTURE_PROVIDER.read_text(encoding="utf-8"))
    prohibited_calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"__import__", "compile", "eval", "exec", "open"}
    }

    assert prohibited_calls == set()
