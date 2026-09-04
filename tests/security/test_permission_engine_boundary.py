from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
PERMISSION_MODULE = ROOT / "src/privilab/application/permissions.py"


def test_permission_engine_has_only_standard_library_and_domain_dependencies() -> None:
    tree = ast.parse(PERMISSION_MODULE.read_text(encoding="utf-8"))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert imported_modules == {
        "__future__",
        "collections.abc",
        "dataclasses",
        "enum",
        "privilab.domain",
        "typing",
    }


def test_permission_engine_cannot_load_or_execute_external_policy_content() -> None:
    tree = ast.parse(PERMISSION_MODULE.read_text(encoding="utf-8"))
    prohibited_calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"__import__", "compile", "eval", "exec", "open"}
    }

    assert prohibited_calls == set()
