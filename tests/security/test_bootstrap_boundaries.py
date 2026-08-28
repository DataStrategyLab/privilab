import tomllib
from fnmatch import fnmatchcase
from pathlib import Path

from privilab.config import load_settings

ROOT = Path(__file__).parents[2]


def test_runtime_dependencies_exclude_prohibited_integrations() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dependencies = " ".join(project["project"]["dependencies"]).lower()

    for prohibited in ("openai", "mcp", "langchain", "autogen", "sqlalchemy"):
        assert prohibited not in dependencies


def test_configuration_does_not_require_api_credentials() -> None:
    settings = load_settings({})

    assert settings.host == "127.0.0.1"
    assert not hasattr(settings, "api_key")


def test_live_eval_workflow_fails_closed() -> None:
    workflow = (ROOT / ".github/workflows/live-eval.yml").read_text()

    assert "workflow_dispatch" in workflow
    assert "blocked until P0-10" in workflow
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
        "fixtures",
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

    assert is_included("src/privilab/evals/__init__.py")
    assert not is_included("evals/golden/example.json")
