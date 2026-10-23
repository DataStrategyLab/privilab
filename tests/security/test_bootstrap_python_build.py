"""Bootstrap rejects existing interpreters without the governed build identity."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize("build", ("20261020", "missing", "20261021", "fresh", "venv"))
def test_bootstrap_checks_existing_and_installed_python_build(
    tmp_path: Path, build: str
) -> None:
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/bootstrap.sh", tmp_path / "scripts/bootstrap.sh")
    (tmp_path / "configs").mkdir()
    shutil.copy(ROOT / "configs/python-downloads-3.13.17.json", tmp_path / "configs")
    for name in ("pyproject.toml", "uv.lock"):
        (tmp_path / name).touch()
    tools = tmp_path / ".tools/bin"
    tools.mkdir(parents=True)
    python_root = tmp_path / "managed"
    if build != "fresh":
        (python_root / "bin").mkdir(parents=True)
        (python_root / "bin/python3.13").touch()
        if build != "missing":
            (python_root / "BUILD").write_text("20261021" if build == "venv" else build)
    if build == "venv":
        (tmp_path / ".venv/bin").mkdir(parents=True)
        (tmp_path / ".venv/bin/python").symlink_to(python_root / "bin/python3.13")
    uv = tools / "uv"
    uv.write_text(
        """#!/bin/sh
set -eu
test "$UV_PYTHON_CPYTHON_BUILD" = 20261021
case "$1" in
  --version) echo 'uv 0.13.4' ;;
  python)
    case "$2" in
      find) test "$4" = --system
            test "$5" = --resolve-links
            test -f "$TEST_PYTHON_ROOT/bin/python3.13"
            echo "$TEST_PYTHON_ROOT/bin/python3.13" ;;
      install) test "$3" = --no-bin
               mkdir -p "$TEST_PYTHON_ROOT/bin"
               touch "$TEST_PYTHON_ROOT/bin/python3.13"
               printf 20261021 > "$TEST_PYTHON_ROOT/BUILD" ;;
    esac ;;
  sync) printf '%s\\n' "$@" > sync-arguments ;;
esac
"""
    )
    uv.chmod(0o755)
    gitleaks = tools / "gitleaks"
    gitleaks.write_text("#!/bin/sh\necho 8.30.1\n")
    gitleaks.chmod(0o755)
    result = subprocess.run(
        ["sh", "scripts/bootstrap.sh", "--ci"],
        cwd=tmp_path,
        env={
            **os.environ,
            "TEST_PYTHON_ROOT": str(python_root),
            "UV_PYTHON_CPYTHON_BUILD": "untrusted-environment-override",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    if build in {"20261020", "missing"}:
        assert result.returncode != 0
        assert "build provenance mismatch" in result.stderr
        assert not (tmp_path / "sync-arguments").exists()
    else:
        assert result.returncode == 0, result.stderr
        arguments = (tmp_path / "sync-arguments").read_text().splitlines()
        assert arguments[arguments.index("--python") + 1] == str(
            python_root / "bin/python3.13"
        )
