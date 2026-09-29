"""Verify governed fixtures from an isolated non-editable wheel install."""

from __future__ import annotations

import os
import subprocess
import sys
import venv
import zipfile
from pathlib import Path

_RESOURCE_PREFIX = "privilab/adapters/models/resources/governed_fixtures/"
_RESOURCE_FILES = {
    f"{_RESOURCE_PREFIX}trade_regulatory_grounded_v1.json",
    f"{_RESOURCE_PREFIX}trade_regulatory_insufficient_source_v1.json",
    f"{_RESOURCE_PREFIX}trade_regulatory_missing_citation_v1.json",
    f"{_RESOURCE_PREFIX}trade_regulatory_missing_chunk_v1.json",
    f"{_RESOURCE_PREFIX}manifest.json",
    f"{_RESOURCE_PREFIX}synthetic_citation_failure_v1.json",
    f"{_RESOURCE_PREFIX}synthetic_happy_path_v1.json",
    f"{_RESOURCE_PREFIX}synthetic_malformed_output_v1.json",
}
_FIXTURE_IDS = (
    "model-output.trade-regulatory-grounded.001",
    "model-output.trade-regulatory-insufficient-source.001",
    "model-output.trade-regulatory-missing-citation.001",
    "model-output.trade-regulatory-missing-chunk.001",
    "model-output.synthetic-happy-path.001",
    "model-output.synthetic-citation-failure.001",
    "model-output.synthetic-malformed.001",
)


def _environment_without_source_path() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONHOME", "PYTHONPATH"}
    }


def verify_built_package(wheel: Path, work_root: Path) -> None:
    """Install one wheel in isolation and load every governed resource."""
    wheel = wheel.resolve(strict=True)
    if wheel.suffix != ".whl":
        raise ValueError("built package verification requires a wheel")
    with zipfile.ZipFile(wheel) as archive:
        packaged_resources = {
            name
            for name in archive.namelist()
            if name.startswith(_RESOURCE_PREFIX) and not name.endswith("/")
        }
    if packaged_resources != _RESOURCE_FILES:
        raise ValueError(
            "built wheel governed resources do not match the canonical inventory"
        )

    work_root.mkdir(parents=True)
    environment = _environment_without_source_path()
    virtual_environment = work_root / "venv"
    venv.EnvBuilder(with_pip=True).create(virtual_environment)
    python = virtual_environment / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    subprocess.run(
        [
            str(python),
            "-I",
            "-m",
            "pip",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "install",
            "--no-index",
            "--no-deps",
            str(wheel),
        ],
        check=True,
        cwd=work_root,
        env=environment,
        stdout=subprocess.DEVNULL,
    )
    smoke = "\n".join(
        (
            "import sys",
            "from pathlib import Path",
            "import privilab",
            "from privilab.adapters.models import load_governed_fixture",
            "assert Path(privilab.__file__).resolve().is_relative_to("
            "Path(sys.prefix).resolve())",
            f"fixture_ids = {_FIXTURE_IDS!r}",
            "bindings = [load_governed_fixture(value) for value in fixture_ids]",
            "assert [binding.model_id for binding in bindings] == list(fixture_ids)",
            "assert all(binding.content_hash.startswith('sha256:') "
            "for binding in bindings)",
        )
    )
    subprocess.run(
        [str(python), "-I", "-c", smoke],
        check=True,
        cwd=work_root,
        env=environment,
    )


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_built_package.py WHEEL WORK_ROOT")
    verify_built_package(Path(sys.argv[1]), Path(sys.argv[2]))
    print("built package governed-resource smoke passed")


if __name__ == "__main__":
    main()
