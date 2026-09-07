"""Validate the deterministic, offline DSL-106 fixture substrate."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Literal

import yaml

from privilab.domain.context import SyntheticRequestContext
from privilab.domain.permissions import PermissionResult

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = (
    ROOT / "fixtures/contexts/manifest.json",
    ROOT / "fixtures/permissions/manifest.json",
    ROOT / "fixtures/corpus/manifest.json",
)
PERMISSION_STATES = {"ALLOW", "CONDITIONAL", "BLOCK", "UNKNOWN"}
CORPUS_PAYLOAD_FIELDS = {"document_id", "title", "text", "synthetic"}
MANIFEST_ENTRY_FIELDS = {
    "id",
    "version",
    "path",
    "content_hash",
    "synthetic",
    "license_ref",
}
CORPUS_RECORD_FIELDS = MANIFEST_ENTRY_FIELDS | {"origin", "permitted_use_basis"}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: top-level value must be an object")
    return value


def require_fields(value: dict[str, Any], fields: set[str], path: Path) -> None:
    missing = fields - set(value)
    if missing:
        raise ValueError(f"{path}: missing fields {sorted(missing)}")


def content_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_fixture_path(manifest_path: Path, raw_path: object) -> Path:
    if not isinstance(raw_path, str) or Path(raw_path).is_absolute():
        raise ValueError(f"{manifest_path}: fixture paths must be relative")
    try:
        fixture_path = (ROOT / raw_path).resolve(strict=True)
        fixture_path.relative_to(manifest_path.parent.resolve())
        fixture_path.relative_to(ROOT.resolve())
    except (OSError, ValueError) as error:
        raise ValueError(
            f"{manifest_path}: fixture path must remain inside its fixture directory"
        ) from error
    if not fixture_path.is_file():
        raise ValueError(f"{manifest_path}: missing fixture {raw_path}")
    return fixture_path


def validate_manifest(
    path: Path,
    registry: dict[str, dict[str, Any]],
    collection_key: Literal["fixtures", "records"],
) -> set[str]:
    manifest = load_json(path)
    expected_manifest_fields = {"schema_version", collection_key}
    manifest_fields = set(manifest)
    alternate_key = "records" if collection_key == "fixtures" else "fixtures"
    if manifest_fields != expected_manifest_fields:
        if alternate_key not in manifest:
            raise ValueError(f"{path}: manifest fields do not match the schema")
        raise ValueError(
            f"{path}: manifest must contain only the {collection_key} collection"
        )
    if manifest["schema_version"] != "1":
        raise ValueError(f"{path}: unsupported schema_version")
    entries = manifest[collection_key]
    if not isinstance(entries, list) or not entries:
        raise ValueError(
            f"{path}: manifest must contain a non-empty {collection_key} collection"
        )

    seen: set[str] = set()
    referenced_paths: set[Path] = set()
    manifest_relative_path = path.resolve().relative_to(ROOT.resolve()).as_posix()
    expected_entry_fields = (
        CORPUS_RECORD_FIELDS if collection_key == "records" else MANIFEST_ENTRY_FIELDS
    )
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: manifest entries must be objects")
        if set(entry) != expected_entry_fields:
            raise ValueError(f"{path}: manifest entry fields do not match the schema")
        fixture_id = entry["id"]
        if (
            not isinstance(fixture_id, str)
            or not fixture_id
            or fixture_id != fixture_id.strip()
            or fixture_id in seen
        ):
            raise ValueError(
                f"{path}: fixture IDs must be unique non-empty, trimmed strings"
            )
        seen.add(fixture_id)
        version = entry["version"]
        if not isinstance(version, str) or not version or version != version.strip():
            raise ValueError(
                f"{path}: fixture versions must be non-empty, trimmed strings"
            )
        if entry["synthetic"] is not True:
            raise ValueError(f"{path}: DSL-106 fixtures must be synthetic")
        fixture_path = resolve_fixture_path(path, entry["path"])
        if fixture_path in referenced_paths:
            raise ValueError(f"{path}: fixture paths must reference unique files")
        referenced_paths.add(fixture_path)
        if entry["content_hash"] != content_hash(fixture_path):
            raise ValueError(f"{path}: stale content hash for {entry['path']}")
        license_ref = entry["license_ref"]
        if license_ref not in registry:
            raise ValueError(f"{path}: unknown license reference {license_ref}")
        license_entry = registry[license_ref]
        registered_paths = set(license_entry.get("repository_paths", []))
        fixture_relative_path = fixture_path.relative_to(ROOT.resolve()).as_posix()
        if (
            license_entry.get("kind") != "fixture"
            or not {
                manifest_relative_path,
                fixture_relative_path,
            }
            <= registered_paths
        ):
            raise ValueError(
                f"{path}: license reference {license_ref} does not cover fixture"
            )
        if license_entry.get("version_or_commit") != version:
            raise ValueError(
                f"{path}: registry version for {license_ref} does not match manifest"
            )

    manifest_files = {
        candidate.resolve()
        for candidate in path.parent.rglob("*.json")
        if candidate.resolve() != path.resolve()
    }
    if manifest_files != referenced_paths:
        raise ValueError(
            f"{path}: all JSON fixtures must be registered in the manifest"
        )
    return seen


def validate_corpus(path: Path, registry: dict[str, dict[str, Any]]) -> None:
    manifest = load_json(path)
    records = manifest.get("records")
    if not isinstance(records, list):
        raise ValueError(f"{path}: corpus manifest must contain records")
    for record in records:
        if not isinstance(record, dict):
            raise ValueError(f"{path}: corpus records must be objects")
        require_fields(record, {"origin", "permitted_use_basis"}, path)
        provenance_values = (record["origin"], record["permitted_use_basis"])
        if any(
            not isinstance(value, str) or not value or value != value.strip()
            for value in provenance_values
        ):
            raise ValueError(
                f"{path}: corpus provenance fields must be non-empty, trimmed strings"
            )
    validate_manifest(path, registry, "records")

    for record in records:
        fixture_path = resolve_fixture_path(path, record["path"])
        try:
            payload = load_json(fixture_path)
            if set(payload) != CORPUS_PAYLOAD_FIELDS:
                raise ValueError("corpus payload fields do not match the schema")
            if payload["synthetic"] is not True:
                raise ValueError("corpus payload must be synthetic")
            for field_name in ("document_id", "title", "text"):
                field_value = payload[field_name]
                if not isinstance(field_value, str) or not field_value.strip():
                    raise ValueError(
                        f"corpus payload {field_name} must contain non-whitespace text"
                    )
        except (OSError, TypeError, ValueError) as error:
            raise ValueError(
                f"{fixture_path}: invalid synthetic corpus payload"
            ) from error


def validate_permission_fixture(
    path: Path, registry: dict[str, dict[str, Any]]
) -> None:
    manifest = load_json(path)
    validate_manifest(path, registry, "fixtures")
    entries = manifest.get("fixtures")
    if not isinstance(entries, list):
        raise ValueError(f"{path}: permission manifest must contain fixtures")

    states: set[object] = set()
    for entry in entries:
        fixture_path = resolve_fixture_path(path, entry["path"])
        payload = load_json(fixture_path)
        if set(payload) != {"fixtures", "synthetic"}:
            raise ValueError(
                f"{fixture_path}: permission fixture fields do not match the schema"
            )
        if payload.get("synthetic") is not True:
            raise ValueError(f"{fixture_path}: permission fixture must be synthetic")
        results = payload.get("fixtures")
        if not isinstance(results, list):
            raise ValueError(f"{fixture_path}: permission fixture must contain results")
        for result in results:
            if not isinstance(result, dict):
                raise ValueError(f"{fixture_path}: permission results must be objects")
            try:
                PermissionResult.from_json(json.dumps(result))
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"{fixture_path}: invalid permission result"
                ) from error
            states.add(result.get("state"))
    if states != PERMISSION_STATES:
        raise ValueError("permission fixture must cover exactly the approved states")


def validate_context_fixture(path: Path, registry: dict[str, dict[str, Any]]) -> None:
    """Validate every context payload selected by a context manifest."""
    manifest = load_json(path)
    validate_manifest(path, registry, "fixtures")
    entries = manifest.get("fixtures")
    if not isinstance(entries, list):
        raise ValueError(f"{path}: context manifest must contain fixtures")

    for entry in entries:
        fixture_path = resolve_fixture_path(path, entry["path"])
        try:
            SyntheticRequestContext.from_json(fixture_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError) as error:
            raise ValueError(
                f"{fixture_path}: invalid synthetic request context"
            ) from error


def validate() -> None:
    registry_value = yaml.safe_load(
        (ROOT / "licenses/registry.yaml").read_text(encoding="utf-8")
    )
    if not isinstance(registry_value, list):
        raise ValueError("licenses/registry.yaml must contain a list")
    registry = {entry["id"]: entry for entry in registry_value}
    if len(registry) != len(registry_value):
        raise ValueError("license registry IDs must be unique")
    for manifest in MANIFESTS:
        if manifest.name == "manifest.json" and "corpus" in manifest.parts:
            validate_corpus(manifest, registry)
        elif "permissions" in manifest.parts:
            validate_permission_fixture(manifest, registry)
        elif "contexts" in manifest.parts:
            validate_context_fixture(manifest, registry)
        else:
            raise ValueError(f"unsupported fixture manifest path: {manifest}")


if __name__ == "__main__":
    try:
        validate()
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as error:
        print(f"fixture validation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print("fixture validation passed")
