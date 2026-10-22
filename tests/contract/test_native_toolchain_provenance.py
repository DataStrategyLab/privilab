"""ADR-011: native Python download catalog and frozen Docker are independent."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
CATALOG = ROOT / "configs/python-downloads-3.13.17.json"
FROZEN_UV = (
    "ghcr.io/astral-sh/uv:0.12.23@sha256:"
    "61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21"
)
FROZEN_PYTHON = (
    "python:3.13.15-slim-bookworm@sha256:"
    "c45a22ea000adfd9cda29364bbe7edd23001ce5cc2ad15857cfbf7766943b9ca"
)
EXPECTED_DIGESTS = {
    "cpython-3.13.17-darwin-aarch64-none": (
        "8dc60610a82f1e73be7faf964383e02520f95f6e39592a5c37c3809f5a7b798e"
    ),
    "cpython-3.13.17-darwin-x86_64-none": (
        "ce9c748c8f7525c0052247edb2435fdb1cac89c77e687e0e199eaf2b827668c2"
    ),
    "cpython-3.13.17-linux-aarch64-gnu": (
        "c6857c65b996701a5da104cbb49b35249c0c026dc0664239b04f7156aa88326a"
    ),
    "cpython-3.13.17-linux-x86_64-gnu": (
        "f829adc9d888e76c8801b4799ed444188d35239fcae3a9808a99ec5cb0d8d92c"
    ),
}


def test_native_python_catalog_is_a_checked_in_local_source() -> None:
    bootstrap = (ROOT / "scripts/bootstrap.sh").read_text(encoding="utf-8")
    assert 'PYTHON_VERSION="3.13.17"' in bootstrap
    assert 'UV_VERSION="0.13.4"' in bootstrap
    assert 'PYTHON_CATALOG="configs/python-downloads-3.13.17.json"' in bootstrap
    assert 'export UV_PYTHON_DOWNLOADS_JSON_URL="$PWD/$PYTHON_CATALOG"' in bootstrap
    assert 'if [ ! -f "$PYTHON_CATALOG" ]; then' in bootstrap
    assert "https://github.com/astral-sh/uv/releases/download/" in bootstrap


def test_native_python_catalog_has_exact_release_assets_and_hashes() -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert set(catalog) == set(EXPECTED_DIGESTS)
    for key, record in catalog.items():
        assert set(record) == {
            "name",
            "arch",
            "os",
            "libc",
            "major",
            "minor",
            "patch",
            "prerelease",
            "url",
            "sha256",
            "variant",
            "build",
        }
        assert record["name"] == "cpython"
        assert (record["major"], record["minor"], record["patch"]) == (3, 13, 17)
        assert record["prerelease"] == ""
        assert record["variant"] is None
        assert record["build"] == "20261021"
        assert record["sha256"] == EXPECTED_DIGESTS[key]
        assert re.fullmatch("[0-9a-f]{64}", record["sha256"])
        assert record["arch"] == {"family": key.split("-")[3], "variant": None}
        assert record["os"] in {"darwin", "linux"}
        assert record["libc"] == ("none" if record["os"] == "darwin" else "gnu")
        assert record["url"].startswith(
            "https://github.com/astral-sh/python-build-standalone/"
            "releases/download/20261021/cpython-3.13.17%2B20261021-"
        )
        assert record["url"].endswith("-install_only_stripped.tar.gz")
        assert "?" not in record["url"]


def assert_docker_hold(documents: dict[str, str]) -> None:
    for name, text in documents.items():
        prose = " ".join(text.lower().split())
        assert "security-qualification hold" in prose, name
        assert "do not build, run or expose it" in prose, name


def docker_hold_documents() -> dict[str, str]:
    return {
        name: (ROOT / name).read_text(encoding="utf-8")
        for name in (
            "README.md",
            "SECURITY.md",
            "docs/release-status.md",
            "docs/getting-started.md",
        )
    }


def test_frozen_docker_references_are_still_exact_and_on_hold() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert FROZEN_UV in dockerfile
    assert FROZEN_PYTHON in dockerfile
    assert_docker_hold(docker_hold_documents())


@pytest.mark.parametrize("name", tuple(docker_hold_documents()))
@pytest.mark.parametrize(
    "removed", ("security-qualification hold", "do not build, run or expose it")
)
def test_removed_docker_hold_is_rejected(name: str, removed: str) -> None:
    documents = {
        key: " ".join(value.lower().split())
        for key, value in docker_hold_documents().items()
    }
    documents[name] = documents[name].replace(removed, "removed restriction")
    with pytest.raises(AssertionError, match=re.escape(name)):
        assert_docker_hold(documents)
