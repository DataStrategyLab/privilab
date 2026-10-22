"""Executable checks for the DSL-105 repository and verification contract."""

from __future__ import annotations

import copy
import re
import stat
import subprocess
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

# Current public entry points only. Historical captures/plans retain their own
# context and are classified separately, not rewritten to satisfy these checks.
PUBLIC_DOCS = (
    "README.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "CONTRIBUTORS.md",
    "GOVERNANCE.md",
    "SUPPORT.md",
    "SECURITY.md",
    "DATA_HANDLING.md",
    "CODE_OF_CONDUCT.md",
    "CHANGELOG.md",
    "ROADMAP.md",
    "THIRD_PARTY_NOTICES.md",
    ".github/CODE_REVIEW.md",
    ".github/pull_request_template.md",
    "docs/README.md",
    "docs/getting-started.md",
    "docs/reproducibility.md",
    "docs/capabilities.md",
    "docs/release-status.md",
    "docs/evidence-publication.md",
    "docs/review/code_review.md",
    "docs/decisions/README.md",
    "docs/decisions/decision-log.md",
    "licenses/README.md",
)

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
    "CONTRIBUTORS.md",
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
    project_override: dict[str, Any] | None = None,
    workflow_override: dict[str, Any] | None = None,
    dockerfile_override: str | None = None,
) -> None:
    entries = registry_by_id(registry)
    uv_version = bootstrap_constant("UV_VERSION")
    gitleaks_version = bootstrap_constant("GITLEAKS_VERSION")
    python_version = bootstrap_constant("PYTHON_VERSION")

    project = project_override or tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    build_requirements = project["build-system"]["requires"]
    assert len(build_requirements) == 1
    build_match = re.fullmatch(r"uv_build==([^\s]+)", build_requirements[0])
    assert build_match, "uv_build must be the sole exact-pinned build backend"
    uv_build_version = build_match.group(1)
    assert uv_build_version == uv_version, "uv_build must match bootstrap UV_VERSION"
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
            "source": (
                "https://github.com/astral-sh/python-build-standalone/releases/tag/20261021"
            ),
            "version_or_commit": (
                f"CPython {python_version} build 20261021 selected by uv {uv_version}"
            ),
            "license_source": (
                "LICENSE.txt bundled in the installed uv-managed CPython "
                f"{python_version} build 20261021 distribution."
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
    # ADR-011: frozen Docker reference provenance is independent of native pins.
    assert uv_image_version == "0.12.23", (
        "Frozen Docker uv tag must remain at the reviewed reference version"
    )
    assert python_image.startswith("python:3.13.15-slim-bookworm@sha256:")
    python_reference = python_image.split(":", maxsplit=1)[1]
    assert uv_digest == (
        "sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21"
    ), "Frozen Docker uv digest must remain immutable"
    assert python_reference == (
        "3.13.15-slim-bookworm@sha256:"
        "c45a22ea000adfd9cda29364bbe7edd23001ce5cc2ad15857cfbf7766943b9ca"
    ), "Frozen Docker Python digest must remain immutable"
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


def assert_public_documentation_url_boundary(text: str, relative_path: str) -> None:
    assert not re.search(
        r"https?://(?:linear\.app|(?:[\w-]+\.)?(?:drive|docs)\.google\.com)"
        r"(?:[/\s]|$)",
        text,
        re.IGNORECASE,
    ), f"{relative_path}: use public references or stable internal issue identifiers"


@pytest.mark.parametrize(
    "url",
    [
        "https://linear.app/example/issue/EXAMPLE-1",
        "https://drive.google.com/file/d/synthetic/view",
        "https://docs.google.com/document/d/synthetic/edit",
        "https://docs.google.com/spreadsheets/d/synthetic/edit",
        "https://docs.google.com/presentation/d/synthetic/edit",
        "HTTPS://DOCS.GOOGLE.COM/forms/d/synthetic/viewform",
    ],
)
def test_private_workflow_links_are_rejected(url: str) -> None:
    with pytest.raises(AssertionError, match="use public references"):
        assert_public_documentation_url_boundary(
            f"[Required record]({url})", "README.md"
        )


@pytest.mark.parametrize(
    "text",
    [
        "https://docs.python.org/3/",
        "https://developers.google.com/docs/api",
        "https://github.com/DataStrategyLab/privilab/issues",
        "Maintainer issue identifier: EXAMPLE-1",
    ],
)
def test_public_references_remain_allowed(text: str) -> None:
    assert_public_documentation_url_boundary(text, "README.md")


@pytest.mark.parametrize("relative_path", PUBLIC_DOCS)
def test_public_documentation_links_and_private_url_boundary(
    relative_path: str,
) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    assert_public_documentation_url_boundary(text, relative_path)

    # Check inline Markdown file links outside fenced examples without network
    # requests. External availability and historical evidence are separate reviews.
    prose = re.sub(r"^```[^\n]*\n.*?^```[^\n]*$", "", text, flags=re.M | re.S)
    for match in re.finditer(r"\[[^\]\n]*\]\(<?([^\s)>]+)>?\)", prose):
        link = urlsplit(match[1])
        if link.scheme or link.netloc:
            continue
        target = (path.parent / unquote(link.path)).resolve() if link.path else path
        assert target.is_relative_to(ROOT), f"{relative_path}: link escapes repository"
        assert target.exists(), f"{relative_path}: missing local target {match[1]}"
        if link.fragment and target.suffix == ".md":
            headings = re.findall(
                r"^#{1,6}\s+(.+?)\s*#*\s*$",
                target.read_text(encoding="utf-8"),
                flags=re.M,
            )
            anchors = {
                re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
                for heading in headings
            }
            assert unquote(link.fragment) in anchors, (
                f"{relative_path}: missing heading target {match[1]}"
            )


def test_public_workflow_does_not_require_private_issue_access() -> None:
    for relative_path in ("AGENTS.md", "CONTRIBUTING.md", "GOVERNANCE.md"):
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        assert re.search(r"public (?:GitHub )?issue", text, re.IGNORECASE)
        assert "maintainer-scoped" in text or "public issue/PR" in text
        assert not re.search(r"work from one Ready Linear issue", text, re.IGNORECASE)
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Drive, or internal planning access is not required" in agents
    assert "make ci" in agents
    assert "non-author human approval" in agents
    assert "Andrew's final merge/release" in agents


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
    assert "model" not in config
    assert "model_reasoning_effort" not in config
    assert config == {
        "review_model": "gpt-6-astra",
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


def test_mismatched_uv_build_version_is_rejected() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project["build-system"]["requires"] = ["uv_build==0.0.0"]
    registry = copy.deepcopy(load_yaml("licenses/registry.yaml"))
    build_entry = registry_by_id(registry)["build:uv-build"]
    build_entry["version_or_commit"] = "0.0.0"
    build_entry["source"] = "https://github.com/astral-sh/uv/tree/0.0.0/crates/uv-build"
    build_entry["license_source"] = "https://github.com/astral-sh/uv/tree/0.0.0#license"

    with pytest.raises(
        AssertionError, match="uv_build must match bootstrap UV_VERSION"
    ):
        assert_reviewed_non_pypi_artifacts_match(registry, project_override=project)


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
        (
            "runtime:python-build-standalone",
            "version_or_commit",
            "CPython 3.13.17 build 20260825 selected by uv 0.13.4",
        ),
        (
            "runtime:python-build-standalone",
            "source",
            "https://github.com/astral-sh/python-build-standalone",
        ),
        (
            "runtime:python-build-standalone",
            "source",
            "https://github.com/astral-sh/python-build-standalone/releases/tag/20260825",
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
        ("uv:0.12.23@", "uv:0.0.0@", "Frozen Docker uv tag"),
        (
            "61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21",
            "0" * 64,
            "Frozen Docker uv digest must remain immutable",
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


def assert_bootstrap_requires_managed_python(bootstrap: str) -> None:
    control = "export UV_MANAGED_PYTHON=true"
    assert control in bootstrap.splitlines(), (
        "bootstrap must export UV_MANAGED_PYTHON=true"
    )
    for operation in (
        '"$UV_BIN" python find "$PYTHON_VERSION"',
        '"$UV_BIN" python install --no-bin "$PYTHON_VERSION"',
        '"$UV_BIN" sync',
    ):
        assert bootstrap.index(control) < bootstrap.index(operation), (
            "managed-Python control must precede bootstrap interpreter operations"
        )


def test_bootstrap_requires_managed_python() -> None:
    bootstrap = (ROOT / "scripts/bootstrap.sh").read_text(encoding="utf-8")
    assert_bootstrap_requires_managed_python(bootstrap)


@pytest.mark.parametrize(
    "replacement",
    [
        "",
        "# export UV_MANAGED_PYTHON=true",
        "export UV_MANAGED_PYTHON=false",
        "UV_MANAGED_PYTHON=true",
        "late",
    ],
    ids=["missing", "commented", "false", "not-exported", "too-late"],
)
def test_bootstrap_without_managed_python_requirement_is_rejected(
    replacement: str,
) -> None:
    bootstrap = (ROOT / "scripts/bootstrap.sh").read_text(encoding="utf-8")
    control = "export UV_MANAGED_PYTHON=true"
    if replacement == "late":
        invalid_bootstrap = bootstrap.replace(control, "") + f"\n{control}\n"
    else:
        invalid_bootstrap = bootstrap.replace(control, replacement)
    assert invalid_bootstrap != bootstrap

    with pytest.raises(AssertionError, match="bootstrap must export|must precede"):
        assert_bootstrap_requires_managed_python(invalid_bootstrap)


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
        "!fixtures/",
        "!fixtures/corpus/",
        "!fixtures/corpus/**",
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
    assert local_copy_sources == {
        "pyproject.toml",
        "uv.lock",
        "README.md",
        "src",
        "fixtures/corpus",
    }
    assert "COPY fixtures/corpus ./fixtures/corpus" in dockerfile
    assert "PRIVILAB_PREVIEW_CORPUS_ROOT=/app/fixtures/corpus" in dockerfile
    assert "PRIVILAB_PREVIEW_DB=/app/.local/preview/provenance.sqlite3" in dockerfile


def test_linear_mcp_exception_and_adr_filename_are_exact() -> None:
    decision_log = (ROOT / "docs/decisions/decision-log.md").read_text(encoding="utf-8")
    assert LINEAR_MCP_DECISION in decision_log
    assert (ROOT / "docs/decisions/ADR-009-independent-review.md").is_file()
    assert not [path for path in ROOT.rglob("*") if "\\" in path.name]


def test_codeowners_and_review_controls_are_finalized() -> None:
    codeowners = (ROOT / ".github/CODEOWNERS").read_text(encoding="utf-8")
    review_controls = (ROOT / "docs/review/code_review.md").read_text(encoding="utf-8")
    contributors = (ROOT / "CONTRIBUTORS.md").read_text(encoding="utf-8")

    assert "@tsintsiruk" in codeowners
    assert "@NaveenGali11" in codeowners
    assert "@adaora-orakwue" not in codeowners
    assert "still required" not in codeowners
    assert "pending" not in codeowners.lower()

    rule_entries = [
        (parts[0], set(parts[1:]))
        for line in codeowners.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
        if (parts := stripped.split())
    ]
    rules = dict(rule_entries)
    assert len(rule_entries) == len(rules), "CODEOWNERS patterns must not be duplicated"
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
    assert all(owners == {"@tsintsiruk", "@NaveenGali11"} for owners in rules.values())

    assert "@tsintsiruk" in review_controls
    assert "@adaora-orakwue" not in review_controls
    assert "@NaveenGali11" in review_controls
    assert "CODEOWNERS is final" in review_controls
    assert "one non-author human approval" in review_controls
    assert "Andrew retains final merge and release authority" in review_controls
    assert "pending" not in review_controls.lower()
    assert "Adaora Orakwue" in contributors
    assert "https://github.com/adaora-orakwue" in contributors


def test_bootstrap_dependency_set_excludes_out_of_scope_components() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = "\n".join(
        project["project"]["dependencies"] + project["dependency-groups"]["dev"]
    ).lower()
    for forbidden in (
        "detect-secrets",
        "httpx",
        "langchain",
        "pytest-cov",
        "sqlalchemy",
    ):
        assert forbidden not in declared


def test_smoke_harness_is_executed_by_ci() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert '"$(PYTHON)" -m privilab.evals.smoke' in makefile
    assert "NOT APPLICABLE / SKIPPED" not in makefile
