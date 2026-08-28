"""Executable checks for the DSL-105 repository and verification contract."""

from __future__ import annotations

import copy
import re
import stat
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_PATHS = {
    ".codex/config.toml",
    ".dockerignore",
    ".env.example",
    ".github/CODEOWNERS",
    ".github/dependabot.yml",
    ".github/pull_request_template.md",
    ".github/workflows/live-eval.yml",
    ".github/workflows/verify.yml",
    ".gitignore",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "DATA_HANDLING.md",
    "Dockerfile",
    "Makefile",
    "PLANS.md",
    "README.md",
    "SECURITY.md",
    "docs/architecture/system.md",
    "docs/architecture/trust-boundaries.md",
    "docs/decisions/ADR-001-application-topology.md",
    "docs/decisions/ADR-002-runtime-boundary.md",
    "docs/decisions/ADR-003-model-provider.md",
    "docs/decisions/ADR-004-retrieval.md",
    "docs/decisions/ADR-005-permissions.md",
    "docs/decisions/ADR-006-evaluation.md",
    "docs/decisions/ADR-007-provenance.md",
    "docs/decisions/ADR-008-preview-deployment.md",
    "docs/decisions/ADR-009-independent-review.md",
    "docs/decisions/ADR-010-untrusted-content.md",
    "docs/decisions/decision-log.md",
    "docs/product/evidence/README.md",
    "docs/review/code_review.md",
    "evals/candidates/README.md",
    "evals/golden/README.md",
    "evals/holdout/README.md",
    "evals/smoke/README.md",
    "fixtures/contexts/README.md",
    "fixtures/corpus/README.md",
    "fixtures/model_outputs/README.md",
    "fixtures/permissions/README.md",
    "licenses/registry.yaml",
    "pyproject.toml",
    "scripts/bootstrap.sh",
    "scripts/reset_demo.py",
    "scripts/secret_scan.sh",
    "scripts/seed_demo.py",
    "src/privilab/application/run_service.py",
    "src/privilab/config.py",
    "src/privilab/main.py",
    "src/privilab/web/templates/index.html",
    "tasks/trade_regulatory/research_v1/README.md",
    "tests/integration/test_placeholder_app.py",
    "tests/security/test_bootstrap_boundaries.py",
    "tests/unit/test_config.py",
    "uv.lock",
}

LICENSE_FIELDS = {
    "id",
    "kind",
    "name",
    "source",
    "version_or_commit",
    "reviewed_date",
    "license",
    "license_source",
    "intended_use",
    "permitted_use_basis",
    "attribution_required",
    "attribution",
    "restrictions",
    "repository_paths",
    "reviewer",
    "open_questions",
}
LICENSE_OPTIONAL_FIELDS = {"content_hash"}
LICENSE_KINDS = {
    "benchmark",
    "copied-code",
    "dataset",
    "demo-source",
    "dependency",
    "fixture",
    "github-action",
    "model-artifact",
    "reference-only",
}
ACTION_PINS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python": "5fda3b95a4ea91299a34e894583c3862153e4b97",
}
LINEAR_MCP_DECISION = (
    "2026-08-27: Approved Linear MCP for Codex engineering/project-management "
    "access only. This supersedes the Gate 3 bootstrap assumption of no MCP for "
    "engineering sessions. Linear MCP is not part of the PriviLAB runtime, may "
    "not access client/DMS data or deployment credentials, and does not authorize "
    "architecture changes or autonomous merge/release actions. Approved by Andrew."
)


def load_yaml(relative_path: str) -> Any:
    return yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8"))


def bootstrap_constant(name: str) -> str:
    bootstrap = (ROOT / "scripts/bootstrap.sh").read_text(encoding="utf-8")
    match = re.search(rf'^{re.escape(name)}="([^"]+)"$', bootstrap, re.MULTILINE)
    assert match, f"missing bootstrap constant {name}"
    return match.group(1)


def registry_by_id(registry: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    entries = {entry["id"]: entry for entry in registry}
    assert len(entries) == len(registry), "license registry ids must be unique"
    return entries


def assert_reviewed_non_pypi_artifacts_match(
    registry: list[dict[str, Any]],
    *,
    workflow_override: dict[str, Any] | None = None,
    dockerfile_override: str | None = None,
) -> None:
    entries = registry_by_id(registry)
    uv_version = bootstrap_constant("UV_VERSION")
    gitleaks_version = bootstrap_constant("GITLEAKS_VERSION")
    python_version = bootstrap_constant("PYTHON_VERSION")

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    build_requirements = project["build-system"]["requires"]
    assert len(build_requirements) == 1
    build_match = re.fullmatch(r"uv_build==([^\s]+)", build_requirements[0])
    assert build_match, "uv_build must be the sole exact-pinned build backend"
    uv_build_version = build_match.group(1)
    assert project["tool"]["uv"]["required-version"] == f"=={uv_version}"

    expected = {
        "build:uv-build": {
            "kind": "dependency",
            "name": "uv_build",
            "source": (
                "https://github.com/astral-sh/uv/tree/"
                f"{uv_build_version}/crates/uv-build"
            ),
            "version_or_commit": uv_build_version,
            "license_source": (
                f"https://github.com/astral-sh/uv/tree/{uv_build_version}#license"
            ),
            "repository_paths": ["pyproject.toml"],
        },
        "tool:uv": {
            "kind": "dependency",
            "name": "uv",
            "source": f"https://github.com/astral-sh/uv/releases/tag/{uv_version}",
            "version_or_commit": uv_version,
            "license_source": (
                f"https://github.com/astral-sh/uv/tree/{uv_version}#license"
            ),
            "repository_paths": [
                "scripts/bootstrap.sh",
                "Makefile",
                "pyproject.toml",
            ],
        },
        "tool:gitleaks": {
            "kind": "dependency",
            "name": "Gitleaks",
            "source": (
                f"https://github.com/gitleaks/gitleaks/releases/tag/v{gitleaks_version}"
            ),
            "version_or_commit": gitleaks_version,
            "license_source": (
                f"https://github.com/gitleaks/gitleaks/blob/v{gitleaks_version}/LICENSE"
            ),
            "repository_paths": [
                "scripts/bootstrap.sh",
                "scripts/secret_scan.sh",
                "Makefile",
            ],
        },
        "runtime:python-build-standalone": {
            "kind": "dependency",
            "name": "uv-managed CPython distribution",
            "source": "https://github.com/astral-sh/python-build-standalone",
            "version_or_commit": (
                f"CPython {python_version} selected by uv {uv_version}"
            ),
            "license_source": (
                "LICENSE.txt bundled in the installed uv-managed CPython "
                f"{python_version} distribution."
            ),
            "repository_paths": [
                "scripts/bootstrap.sh",
                ".github/workflows/verify.yml",
                "pyproject.toml",
            ],
        },
    }

    workflow = workflow_override or load_yaml(".github/workflows/verify.yml")
    action_steps = [
        step for step in workflow["jobs"]["verify-ci"]["steps"] if "uses" in step
    ]
    setup_python_steps = [
        step
        for step in action_steps
        if step["uses"].startswith("actions/setup-python@")
    ]
    assert len(setup_python_steps) == 1
    workflow_python_version = setup_python_steps[0]["with"]["python-version"]
    assert workflow_python_version == python_version, (
        "GitHub Actions Python version must match bootstrap PYTHON_VERSION"
    )
    for step in action_steps:
        action, commit = step["uses"].split("@", maxsplit=1)
        entry_id = f"action:{action.split('/', maxsplit=1)[1]}"
        expected[entry_id] = {
            "kind": "github-action",
            "name": action,
            "source": f"https://github.com/{action}",
            "version_or_commit": commit,
            "license_source": f"https://github.com/{action}/blob/{commit}/LICENSE",
            "repository_paths": [".github/workflows/verify.yml"],
        }

    dockerfile = dockerfile_override or (ROOT / "Dockerfile").read_text(
        encoding="utf-8"
    )
    from_references = [
        line.split()[1] for line in dockerfile.splitlines() if line.startswith("FROM ")
    ]
    assert len(from_references) == 2
    uv_image, python_image = from_references
    uv_image_match = re.fullmatch(
        r"ghcr\.io/astral-sh/uv:([^@\s]+)@(sha256:[0-9a-f]{64})", uv_image
    )
    assert uv_image_match, "Docker uv image must have an exact tag and SHA-256 digest"
    uv_image_version, uv_digest = uv_image_match.groups()
    assert uv_image_version == uv_version, (
        "Docker uv image tag must match bootstrap UV_VERSION"
    )
    assert python_image.startswith(f"python:{python_version}-slim-bookworm@sha256:")
    python_reference = python_image.split(":", maxsplit=1)[1]
    expected.update(
        {
            "container:uv": {
                "kind": "dependency",
                "name": "uv distroless image",
                "source": "https://github.com/astral-sh/uv/pkgs/container/uv",
                "version_or_commit": f"{uv_image_version}@{uv_digest}",
                "license_source": (
                    f"https://github.com/astral-sh/uv/tree/{uv_image_version}#license"
                ),
                "repository_paths": ["Dockerfile"],
            },
            "container:python": {
                "kind": "dependency",
                "name": "Python Official Image",
                "source": "https://hub.docker.com/_/python",
                "version_or_commit": python_reference,
                "license_source": (
                    "https://github.com/docker-library/python/tree/master/3.13/bookworm"
                ),
                "repository_paths": ["Dockerfile"],
            },
        }
    )

    for entry_id, reviewed_fields in expected.items():
        assert entry_id in entries, f"missing reviewed registry entry {entry_id}"
        entry = entries[entry_id]
        for field, expected_value in reviewed_fields.items():
            assert entry[field] == expected_value, (
                f"stale license evidence for {entry_id}: {field} must match "
                "the implementation reference"
            )


def test_required_paths_are_present() -> None:
    missing = sorted(path for path in REQUIRED_PATHS if not (ROOT / path).exists())
    assert not missing, f"missing required repository paths: {missing}"


@pytest.mark.parametrize(
    "relative_path",
    [
        ".env",
        ".env.production",
        ".env-local",
        ".envrc",
        "demo.sqlite",
        "demo.sqlite-wal",
        "demo.sqlite-shm",
        "demo.sqlite-journal",
        "demo.sqlite3-wal",
        "demo.db-wal",
    ],
)
def test_sensitive_generated_local_files_are_ignored_by_git(
    relative_path: str,
) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", relative_path],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0, f"{relative_path} must be ignored by Git"


def test_env_example_remains_intentionally_trackable() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", ".env.example"],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 1
    assert (ROOT / ".env.example").is_file()


def test_bootstrap_scripts_are_executable() -> None:
    for relative_path in ("scripts/bootstrap.sh", "scripts/secret_scan.sh"):
        mode = (ROOT / relative_path).stat().st_mode
        assert mode & stat.S_IXUSR, f"{relative_path} must be executable"


def test_codex_configuration_matches_approved_local_controls() -> None:
    config = tomllib.loads((ROOT / ".codex/config.toml").read_text(encoding="utf-8"))
    assert config == {
        "model": "gpt-5.6-terra",
        "model_reasoning_effort": "medium",
        "review_model": "gpt-5.6-sol",
        "approval_policy": "on-request",
        "sandbox_mode": "workspace-write",
        "web_search": "disabled",
        "sandbox_workspace_write": {"network_access": False},
        "features": {"multi_agent": False},
    }


def test_verify_workflow_is_least_privilege_and_immutable() -> None:
    workflow = load_yaml(".github/workflows/verify.yml")
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"verify-ci"}
    job = workflow["jobs"]["verify-ci"]
    assert job["name"] == "verify-ci"
    assert job["timeout-minutes"] == 20

    uses = {
        step["uses"].split("@", maxsplit=1)[0]: step
        for step in job["steps"]
        if "uses" in step
    }
    assert set(uses) == set(ACTION_PINS)
    for action, commit in ACTION_PINS.items():
        assert uses[action]["uses"] == f"{action}@{commit}"
    assert uses["actions/checkout"]["with"]["persist-credentials"] is False
    assert [step.get("run") for step in job["steps"] if "run" in step] == [
        "./scripts/bootstrap.sh --ci",
        "make ci",
    ]


def test_non_pypi_artifacts_match_reviewed_registry_evidence() -> None:
    registry = load_yaml("licenses/registry.yaml")
    assert_reviewed_non_pypi_artifacts_match(registry)


@pytest.mark.parametrize(
    ("entry_id", "field", "stale_value"),
    [
        ("tool:uv", "version_or_commit", "0.0.0"),
        ("tool:gitleaks", "version_or_commit", "0.0.0"),
        (
            "runtime:python-build-standalone",
            "version_or_commit",
            "CPython 0.0.0 selected by uv 0.0.0",
        ),
        ("build:uv-build", "version_or_commit", "0.0.0"),
        ("container:uv", "version_or_commit", "0.0.0@sha256:stale"),
        ("container:python", "version_or_commit", "0.0.0@sha256:stale"),
        ("action:checkout", "version_or_commit", "stale"),
        ("action:setup-python", "version_or_commit", "stale"),
        ("tool:uv", "source", "https://example.invalid/stale"),
    ],
)
def test_stale_non_pypi_registry_evidence_is_rejected(
    entry_id: str, field: str, stale_value: str
) -> None:
    registry = copy.deepcopy(load_yaml("licenses/registry.yaml"))
    entries = registry_by_id(registry)
    entries[entry_id][field] = stale_value

    with pytest.raises(AssertionError, match="stale license evidence"):
        assert_reviewed_non_pypi_artifacts_match(registry)


def test_stale_workflow_python_version_is_rejected() -> None:
    registry = load_yaml("licenses/registry.yaml")
    workflow = copy.deepcopy(load_yaml(".github/workflows/verify.yml"))
    setup_python = next(
        step
        for step in workflow["jobs"]["verify-ci"]["steps"]
        if step.get("uses", "").startswith("actions/setup-python@")
    )
    setup_python["with"]["python-version"] = "3.13.14"

    with pytest.raises(AssertionError, match="GitHub Actions Python version"):
        assert_reviewed_non_pypi_artifacts_match(registry, workflow_override=workflow)


@pytest.mark.parametrize(
    ("old_reference", "stale_reference", "message"),
    [
        ("uv:0.12.6@", "uv:0.0.0@", "Docker uv image tag"),
        (
            "88bc6eb1ccd4b82efd0e1b530caffabddf50dc2bf612e66c14ea25b8ee8a4d3d",
            "0" * 64,
            "stale license evidence",
        ),
    ],
)
def test_stale_docker_uv_tag_or_digest_is_rejected(
    old_reference: str, stale_reference: str, message: str
) -> None:
    registry = load_yaml("licenses/registry.yaml")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    stale_dockerfile = dockerfile.replace(old_reference, stale_reference)
    assert stale_dockerfile != dockerfile

    with pytest.raises(AssertionError, match=message):
        assert_reviewed_non_pypi_artifacts_match(
            registry, dockerfile_override=stale_dockerfile
        )


def test_license_registry_uses_the_approved_schema() -> None:
    registry = load_yaml("licenses/registry.yaml")
    assert isinstance(registry, list)
    assert registry

    ids: list[str] = []
    for entry in registry:
        assert LICENSE_FIELDS <= set(entry)
        assert set(entry) <= LICENSE_FIELDS | LICENSE_OPTIONAL_FIELDS
        assert entry["kind"] in LICENSE_KINDS
        assert isinstance(entry["repository_paths"], list)
        assert entry["repository_paths"]
        ids.append(entry["id"])
    assert len(ids) == len(set(ids)), "license registry ids must be unique"


def test_registered_repository_paths_exist() -> None:
    registry = load_yaml("licenses/registry.yaml")
    for entry in registry:
        for relative_path in entry["repository_paths"]:
            assert (ROOT / relative_path).exists(), (
                f"{entry['id']} references missing path {relative_path}"
            )


def test_locked_python_artifacts_are_registered() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked = {
        (package["name"], package["version"])
        for package in lock["package"]
        if package["name"] != "privilab"
    }
    registry = load_yaml("licenses/registry.yaml")
    registered_entries = [
        entry
        for entry in registry
        if entry["kind"] == "dependency"
        and entry["source"].startswith("https://pypi.org/project/")
    ]
    registered = {
        (entry["name"].lower(), entry["version_or_commit"])
        for entry in registered_entries
    }

    assert len(registered) == len(registered_entries), (
        "each locked Python artifact must have one registry entry"
    )
    assert registered == locked
    for entry in registered_entries:
        assert entry["source"] == (
            f"https://pypi.org/project/{entry['name']}/{entry['version_or_commit']}/"
        )


def test_bootstrap_reuses_the_pinned_uv_version() -> None:
    bootstrap = (ROOT / "scripts/bootstrap.sh").read_text(encoding="utf-8")
    assert "awk 'NR == 1 {print $2}'" in bootstrap
    assert '!= "uv $UV_VERSION"' not in bootstrap


def test_bootstrap_keeps_managed_python_out_of_user_global_launchers() -> None:
    bootstrap = (ROOT / "scripts/bootstrap.sh").read_text(encoding="utf-8")
    assert (
        'UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-.local/python}"' in bootstrap
    )
    assert '"$UV_BIN" python install --no-bin "$PYTHON_VERSION"' in bootstrap
    assert '"$UV_BIN" python install "$PYTHON_VERSION"' not in bootstrap


def test_preview_uses_the_documented_environment_variables() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "$${PRIVILAB_HOST:-127.0.0.1}" in makefile
    assert "$${PRIVILAB_PORT:-8000}" in makefile
    assert "$${HOST:-127.0.0.1}" not in makefile
    assert "$${PORT:-8000}" not in makefile


def test_container_bases_are_digest_pinned() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    from_lines = [line for line in dockerfile.splitlines() if line.startswith("FROM ")]
    assert len(from_lines) == 2
    assert all(re.search(r"@sha256:[0-9a-f]{64}(?:\s|$)", line) for line in from_lines)


def test_docker_context_is_default_deny_and_minimal() -> None:
    rules = [
        line
        for raw_line in (ROOT / ".dockerignore")
        .read_text(encoding="utf-8")
        .splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    ]
    assert rules[0] == "**"
    assert {rule for rule in rules if rule.startswith("!")} == {
        "!Dockerfile",
        "!.dockerignore",
        "!README.md",
        "!pyproject.toml",
        "!uv.lock",
        "!src/",
        "!src/**",
    }
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
        "**/*.egg-info",
        "**/*.egg-info/**",
        "**/build",
        "**/build/**",
        "**/dist",
        "**/dist/**",
        "**/.coverage",
        "**/.coverage.*",
        "**/coverage.xml",
        "**/htmlcov",
        "**/htmlcov/**",
        "**/*.sqlite",
        "**/*.sqlite-*",
        "**/*.sqlite3",
        "**/*.sqlite3-*",
        "**/*.db",
        "**/*.db-*",
        "**/*.log",
        "**/logs",
        "**/logs/**",
        "**/*.tmp",
        "**/*.temp",
        "**/.DS_Store",
        "**/output",
        "**/output/**",
        "**/outputs",
        "**/outputs/**",
        "**/runtime",
        "**/runtime/**",
    } <= set(rules)
    assert rules.index("**/.env*") > rules.index("!src/**")
    assert "**/evals" not in rules
    assert "**/evals/**" not in rules

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    local_copy_sources = {
        source
        for line in dockerfile.splitlines()
        if line.startswith("COPY ") and not line.startswith("COPY --from=")
        for source in line.split()[1:-1]
    }
    assert local_copy_sources == {"pyproject.toml", "uv.lock", "README.md", "src"}


def test_linear_mcp_exception_and_adr_filename_are_exact() -> None:
    decision_log = (ROOT / "docs/decisions/decision-log.md").read_text(encoding="utf-8")
    assert LINEAR_MCP_DECISION in decision_log
    assert (ROOT / "docs/decisions/ADR-009-independent-review.md").is_file()
    assert not [path for path in ROOT.rglob("*") if "\\" in path.name]


def test_codeowners_and_review_controls_are_finalized() -> None:
    codeowners = (ROOT / ".github/CODEOWNERS").read_text(encoding="utf-8")
    review_controls = (ROOT / "docs/review/code_review.md").read_text(encoding="utf-8")

    assert "@tsintsiruk" in codeowners
    assert "@adaora-orakwue" in codeowners
    assert "Adaora's verified GitHub handle" not in codeowners
    assert "still required" not in codeowners
    assert "pending" not in codeowners.lower()

    rules = {
        parts[0]: set(parts[1:])
        for line in codeowners.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
        if (parts := stripped.split())
    }
    expected_patterns = {
        "*",
        "/.github/",
        "/.codex/",
        "/AGENTS.md",
        "/SECURITY.md",
        "/DATA_HANDLING.md",
        "/Dockerfile",
        "/Makefile",
        "/pyproject.toml",
        "/uv.lock",
        "/docs/architecture/",
        "/docs/decisions/",
        "/docs/review/",
        "/licenses/",
        "/scripts/bootstrap.sh",
        "/scripts/secret_scan.sh",
        "/src/privilab/adapters/",
        "/src/privilab/config.py",
        "/src/privilab/domain/",
    }
    assert set(rules) == expected_patterns
    assert all(
        owners == {"@tsintsiruk", "@adaora-orakwue"} for owners in rules.values()
    )

    assert "@tsintsiruk" in review_controls
    assert "@adaora-orakwue" in review_controls
    assert "CODEOWNERS is final" in review_controls
    assert "one non-author human approval" in review_controls
    assert "Andrew retains final merge and release authority" in review_controls
    assert "pending" not in review_controls.lower()


def test_bootstrap_dependency_set_excludes_out_of_scope_components() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = "\n".join(
        project["project"]["dependencies"] + project["dependency-groups"]["dev"]
    ).lower()
    for forbidden in (
        "detect-secrets",
        "httpx",
        "langchain",
        "openai",
        "pytest-cov",
        "sqlalchemy",
    ):
        assert forbidden not in declared


def test_smoke_placeholder_is_not_product_evidence() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "NOT APPLICABLE / SKIPPED" in makefile
    assert "not PASS" in makefile
    assert "not product-eval evidence" in makefile
