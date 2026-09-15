"""Verified local composition for governed synthetic model-output fixtures."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from privilab.adapters.models.fixture import FixtureModelProvider
from privilab.application.model_provider import (
    GovernedFixtureBinding,
    _authorized_governed_fixture_binding,
)

_CONTENT_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MANIFEST_FIELDS = {"schema_version", "fixtures"}
_RECORD_FIELDS = {
    "id",
    "version",
    "path",
    "content_hash",
    "synthetic",
    "license_ref",
}
_PROVIDER_ID = "fixture-model-provider"
_PROVIDER_VERSION = "1"
_LICENSE_REF = "fixture:synthetic-model-outputs"
_CANONICAL_MANIFEST = Path("fixtures/model_outputs/manifest.json")
_MODULE_PATH = Path("src/privilab/adapters/models/governed_fixture.py")
_FIXTURE_LOAD_AUTHORITY = object()


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        decoded: object = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_fields,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load governed fixture manifest: {path}") from error
    if not isinstance(decoded, dict) or set(decoded) != _MANIFEST_FIELDS:
        raise ValueError("governed fixture manifest fields are invalid")
    if decoded["schema_version"] != "1":
        raise ValueError("unsupported governed fixture manifest schema")
    fixtures = decoded["fixtures"]
    if not isinstance(fixtures, list) or not fixtures:
        raise ValueError("governed fixture manifest must contain fixtures")
    return decoded


def _resolve_inside(base: Path, relative_path: str, *, boundary: Path) -> Path:
    candidate = Path(relative_path) if isinstance(relative_path, str) else None
    if candidate is None or candidate.is_absolute():
        raise ValueError("governed fixture paths must be relative")
    if ".." in candidate.parts:
        raise ValueError("governed fixture paths must not contain traversal")
    try:
        resolved = (base / candidate).resolve(strict=True)
        resolved.relative_to(boundary)
    except (OSError, ValueError) as error:
        raise ValueError(
            "governed fixture path escapes its approved boundary"
        ) from error
    if not resolved.is_file():
        raise ValueError("governed fixture path must identify a file")
    return resolved


def _canonical_repository_root() -> Path:
    """Resolve the repository-owned fixture authority from this module only."""
    try:
        module = Path(__file__).resolve(strict=True)
        root = module.parents[4]
        expected_module = (root / _MODULE_PATH).resolve(strict=True)
    except (IndexError, OSError) as error:
        raise ValueError(
            "cannot resolve the trusted PriviLAB repository layout"
        ) from error
    if expected_module != module or not (root / "pyproject.toml").is_file():
        raise ValueError("cannot resolve the trusted PriviLAB repository layout")
    return root


def _load_governed_fixture(
    repository_root: str | Path,
    manifest_path: str | Path,
    fixture_id: str,
    *,
    _authorized: object | None = None,
) -> GovernedFixtureBinding:
    """Load one exact manifest record, verify its bytes, and bind its provider."""
    if _authorized is not _FIXTURE_LOAD_AUTHORITY:
        raise TypeError("alternate governed fixture roots are not a public API")
    if not isinstance(repository_root, (str, Path)):
        raise TypeError("repository_root must be a string or Path")
    if not isinstance(manifest_path, (str, Path)):
        raise TypeError("manifest_path must be a string or Path")
    if (
        not isinstance(fixture_id, str)
        or not fixture_id
        or (fixture_id != fixture_id.strip())
    ):
        raise ValueError("fixture_id must be a non-empty, trimmed string")
    try:
        root = Path(repository_root).resolve(strict=True)
    except OSError as error:
        raise ValueError("repository_root must exist") from error
    if not root.is_dir():
        raise ValueError("repository_root must be a directory")
    manifest_relative = Path(manifest_path)
    if manifest_relative.is_absolute():
        raise ValueError("manifest_path must be repository-relative")
    manifest = _resolve_inside(
        root,
        manifest_relative.as_posix(),
        boundary=root,
    )
    payload = _load_manifest(manifest)
    fixtures = payload["fixtures"]
    assert isinstance(fixtures, list)
    matches = [
        record
        for record in fixtures
        if isinstance(record, dict) and record.get("id") == fixture_id
    ]
    if len(matches) != 1:
        raise ValueError("governed fixture identity is missing or duplicated")
    record = matches[0]
    if set(record) != _RECORD_FIELDS:
        raise ValueError("governed fixture record fields are invalid")
    model_id = record["id"]
    model_version = record["version"]
    content_hash = record["content_hash"]
    raw_path = record["path"]
    if not isinstance(model_id, str) or model_id != fixture_id:
        raise ValueError("governed fixture identity is invalid")
    if (
        not isinstance(model_version, str)
        or not model_version
        or (model_version != model_version.strip())
    ):
        raise ValueError("governed fixture version is invalid")
    if not isinstance(content_hash, str) or not _CONTENT_HASH.fullmatch(content_hash):
        raise ValueError("governed fixture content hash is invalid")
    if record["synthetic"] is not True or record["license_ref"] != _LICENSE_REF:
        raise ValueError("governed fixture trust metadata is invalid")
    if not isinstance(raw_path, str):
        raise ValueError("governed fixture path is invalid")
    fixture_path = _resolve_inside(root, raw_path, boundary=manifest.parent.resolve())
    try:
        fixture_bytes = fixture_path.read_bytes()
        output_json = fixture_bytes.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError("governed fixture payload must be readable UTF-8") from error
    actual_hash = f"sha256:{hashlib.sha256(fixture_bytes).hexdigest()}"
    if actual_hash != content_hash:
        raise ValueError("governed fixture content hash does not match its bytes")
    provider = FixtureModelProvider(output_json)
    return _authorized_governed_fixture_binding(
        provider=provider,
        model_id=model_id,
        model_version=model_version,
        content_hash=content_hash,
        provider_id=_PROVIDER_ID,
        provider_version=_PROVIDER_VERSION,
    )


def _load_governed_fixture_for_testing(
    repository_root: str | Path,
    manifest_path: str | Path,
    fixture_id: str,
) -> GovernedFixtureBinding:
    """Exercise fixture validation against an isolated test-only repository."""
    return _load_governed_fixture(
        repository_root,
        manifest_path,
        fixture_id,
        _authorized=_FIXTURE_LOAD_AUTHORITY,
    )


def load_governed_fixture(fixture_id: str) -> GovernedFixtureBinding:
    """Load one fixture from the repository-owned canonical manifest."""
    root = _canonical_repository_root()
    canonical_manifest = root / _CANONICAL_MANIFEST
    try:
        resolved_manifest = canonical_manifest.resolve(strict=True)
    except OSError as error:
        raise ValueError(
            "canonical governed fixture manifest is unavailable"
        ) from error
    if resolved_manifest != canonical_manifest or not canonical_manifest.is_file():
        raise ValueError("canonical governed fixture manifest is unavailable")
    return _load_governed_fixture(
        root,
        _CANONICAL_MANIFEST,
        fixture_id,
        _authorized=_FIXTURE_LOAD_AUTHORITY,
    )


__all__ = ["load_governed_fixture"]
