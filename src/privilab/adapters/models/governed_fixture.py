"""Verified local composition for governed synthetic model-output fixtures."""

from __future__ import annotations

import hashlib
import json
import re
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
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
_RESOURCE_PACKAGE = "privilab.adapters.models"
_RESOURCE_DIRECTORY = ("resources", "governed_fixtures")
_MANIFEST_NAME = "manifest.json"
_FIXTURE_LOAD_AUTHORITY = object()


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _load_manifest(resource: Traversable) -> dict[str, Any]:
    try:
        decoded: object = json.loads(
            resource.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_fields,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("cannot load governed fixture manifest") from error
    if not isinstance(decoded, dict) or set(decoded) != _MANIFEST_FIELDS:
        raise ValueError("governed fixture manifest fields are invalid")
    if decoded["schema_version"] != "1":
        raise ValueError("unsupported governed fixture manifest schema")
    fixtures = decoded["fixtures"]
    if not isinstance(fixtures, list) or not fixtures:
        raise ValueError("governed fixture manifest must contain fixtures")
    seen_ids: set[str] = set()
    for record in fixtures:
        if not isinstance(record, dict) or set(record) != _RECORD_FIELDS:
            raise ValueError("governed fixture record fields are invalid")
        fixture_id = record["id"]
        if (
            not isinstance(fixture_id, str)
            or not fixture_id
            or fixture_id != fixture_id.strip()
            or fixture_id in seen_ids
        ):
            raise ValueError("governed fixture identity is missing or duplicated")
        seen_ids.add(fixture_id)
    return decoded


def _join_resource(resource: Traversable, *parts: str) -> Traversable:
    for part in parts:
        resource = resource.joinpath(part)
    return resource


def _resolve_inside(base: Traversable, relative_path: object) -> Traversable:
    if not isinstance(relative_path, str):
        raise ValueError("governed fixture path is invalid")
    candidate = PurePosixPath(relative_path)
    if not relative_path or candidate.is_absolute():
        raise ValueError("governed fixture paths must be relative")
    if "\\" in relative_path or ".." in candidate.parts:
        raise ValueError("governed fixture paths must not contain traversal")
    resource = _join_resource(base, *candidate.parts)
    if isinstance(base, Path) and isinstance(resource, Path):
        try:
            boundary = base.resolve(strict=True)
            resolved = resource.resolve(strict=True)
            resolved.relative_to(boundary)
        except (OSError, ValueError) as error:
            raise ValueError(
                "governed fixture path escapes its approved boundary"
            ) from error
        resource = resolved
    try:
        is_file = resource.is_file()
    except OSError as error:
        raise ValueError("governed fixture path must identify a file") from error
    if not is_file:
        raise ValueError("governed fixture path must identify a file")
    return resource


def _canonical_resource_root() -> Traversable:
    """Resolve the package-owned fixture authority without filesystem discovery."""
    try:
        package_root = files(_RESOURCE_PACKAGE)
        resource_root = _join_resource(package_root, *_RESOURCE_DIRECTORY)
        if isinstance(package_root, Path) and isinstance(resource_root, Path):
            boundary = package_root.resolve(strict=True)
            resolved = resource_root.resolve(strict=True)
            resolved.relative_to(boundary)
            resource_root = resolved
        if not resource_root.is_dir():
            raise ValueError
    except (ModuleNotFoundError, OSError, TypeError, ValueError) as error:
        raise ValueError(
            "canonical governed fixture resources are unavailable"
        ) from error
    return resource_root


def _load_governed_fixture(
    resource_root: Traversable,
    fixture_id: str,
    *,
    _authorized: object | None = None,
) -> GovernedFixtureBinding:
    """Load one exact manifest record, verify its bytes, and bind its provider."""
    if _authorized is not _FIXTURE_LOAD_AUTHORITY:
        raise TypeError("alternate governed fixture roots are not a public API")
    if (
        not isinstance(fixture_id, str)
        or not fixture_id
        or (fixture_id != fixture_id.strip())
    ):
        raise ValueError("fixture_id must be a non-empty, trimmed string")
    manifest = _resolve_inside(resource_root, _MANIFEST_NAME)
    payload = _load_manifest(manifest)
    fixtures = payload["fixtures"]
    assert isinstance(fixtures, list)
    matches = [record for record in fixtures if record["id"] == fixture_id]
    if len(matches) != 1:
        raise ValueError("governed fixture identity is missing or duplicated")
    record = matches[0]
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
    fixture_resource = _resolve_inside(resource_root, raw_path)
    try:
        fixture_bytes = fixture_resource.read_bytes()
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
    resource_root: str | Path,
    fixture_id: str,
) -> GovernedFixtureBinding:
    """Exercise resource validation against an isolated test-only directory."""
    if not isinstance(resource_root, (str, Path)):
        raise TypeError("resource_root must be a string or Path")
    try:
        resolved_root = Path(resource_root).resolve(strict=True)
    except OSError as error:
        raise ValueError("resource_root must exist") from error
    if not resolved_root.is_dir():
        raise ValueError("resource_root must be a directory")
    return _load_governed_fixture(
        resolved_root,
        fixture_id,
        _authorized=_FIXTURE_LOAD_AUTHORITY,
    )


def load_governed_fixture(fixture_id: str) -> GovernedFixtureBinding:
    """Load one fixture from the package-owned canonical manifest."""
    return _load_governed_fixture(
        _canonical_resource_root(),
        fixture_id,
        _authorized=_FIXTURE_LOAD_AUTHORITY,
    )


__all__ = ["load_governed_fixture"]
