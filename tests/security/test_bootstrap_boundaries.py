import tomllib
from fnmatch import fnmatchcase
from pathlib import Path

from privilab.config import load_settings

ROOT = Path(__file__).parents[2]


def test_runtime_dependencies_exclude_prohibited_integrations() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dependencies = " ".join(project["project"]["dependencies"]).lower()

    assert "openai>=3.19.2,<4" in project["project"]["dependencies"]
    assert "openai[" not in dependencies
    for prohibited in (
        "mcp",
        "langchain",
        "autogen",
        "sqlalchemy",
        "anthropic",
        "litellm",
    ):
        assert prohibited not in dependencies


def test_configuration_does_not_require_api_credentials() -> None:
    settings = load_settings({})

    assert settings.host == "127.0.0.1"
    assert not hasattr(settings, "api_key")


def test_live_eval_workflow_fails_closed() -> None:
    workflow = (ROOT / ".github/workflows/live-eval.yml").read_text()

    assert "workflow_dispatch" in workflow
    assert "blocked pending DSL-116" in workflow
    assert "exit 1" in workflow
    assert "secrets." not in workflow


def test_sensitive_and_generated_state_is_excluded_from_docker_context() -> None:
    rules = [
        line
        for raw_line in (ROOT / ".dockerignore").read_text().splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    ]
    assert rules[0] == "**", "Docker context must default to excluding everything"

    allowed = {rule.removeprefix("!") for rule in rules if rule.startswith("!")}
    forbidden_roots = {
        ".git",
        ".github",
        ".venv",
        ".tools",
        ".local",
        ".env",
        ".env.example",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "build",
        "dist",
        "docs",
        "evals",
        "licenses",
        "scripts",
        "tasks",
        "tests",
    }
    allowed_roots = {path.split("/", maxsplit=1)[0] for path in allowed}
    assert forbidden_roots.isdisjoint(allowed_roots)

    assert {
        "**/.env*",
        "**/.git",
        "**/.git/**",
        "**/.local",
        "**/.local/**",
        "**/.tools",
        "**/.tools/**",
        "**/.venv",
        "**/.venv/**",
        "**/__pycache__",
        "**/__pycache__/**",
        "**/*.py[cod]",
        "**/.pytest_cache",
        "**/.pytest_cache/**",
        "**/.mypy_cache",
        "**/.mypy_cache/**",
        "**/.ruff_cache",
        "**/.ruff_cache/**",
        "**/.cache",
        "**/.cache/**",
        "**/build",
        "**/build/**",
        "**/dist",
        "**/dist/**",
        "**/.coverage",
        "**/.coverage.*",
        "**/*.sqlite",
        "**/*.sqlite3",
        "**/*.db",
        "**/*.log",
        "**/*.tmp",
        "**/.DS_Store",
        "**/.idea",
        "**/.idea/**",
        "**/.vscode",
        "**/.vscode/**",
        "**/output",
        "**/output/**",
        "**/outputs",
        "**/outputs/**",
        "**/runtime",
        "**/runtime/**",
    } <= set(rules)

    protected_examples = {
        "src/privilab/.env",
        "src/privilab/.env.production",
        "src/privilab/.env-local",
        "src/privilab/.envrc",
        "src/privilab/.git/config",
        "src/privilab/.local/python/runtime",
        "src/privilab/.tools/bin/tool",
        "src/privilab/.venv/bin/python",
        "src/privilab/__pycache__/main.pyc",
        "src/privilab/.pytest_cache/state",
        "src/privilab/build/generated.whl",
        "src/privilab/runtime/session.sqlite",
    }

    def is_included(path: str) -> bool:
        matching_rules = [
            rule for rule in rules if fnmatchcase(path, rule.removeprefix("!"))
        ]
        assert matching_rules, f"no Docker context rule matched {path}"
        return matching_rules[-1].startswith("!")

    for path in protected_examples:
        assert not is_included(path), (
            f"sensitive/generated path would enter Docker context: {path}"
        )

    assert {path for path in allowed if path.startswith("fixtures")} == {
        "fixtures/",
        "fixtures/corpus/",
        "fixtures/corpus/**",
    }
    for name in (
        "manifest.json",
        "synthetic_injection_v1.json",
        "synthetic_trade_notice_v1.json",
    ):
        assert is_included(f"fixtures/corpus/{name}")
    for name in (
        "permissions/policy.json",
        "contexts/context.json",
        "model_outputs/answer.json",
    ):
        assert not is_included(f"fixtures/{name}")
    for path in protected_examples:
        assert not is_included(path.replace("src/privilab", "fixtures/corpus"))
    assert is_included("src/privilab/evals/__init__.py")
    assert not is_included("evals/golden/example.json")
