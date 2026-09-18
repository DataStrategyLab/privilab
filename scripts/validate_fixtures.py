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
from privilab.domain.research import CitationReference, ResearchResult

ROOT = Path(__file__).resolve().parents[1]
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
FIXTURE_DOCUMENTATION_PATHS = {
    Path("fixtures/contexts/README.md"),
    Path("fixtures/corpus/README.md"),
    Path("fixtures/model_outputs/README.md"),
    Path("fixtures/permissions/README.md"),
}
MODEL_OUTPUT_FIXTURES = {
    "model-output.synthetic-happy-path.001": (
        "1.0.0",
        "synthetic_happy_path_v1.json",
        "happy-path",
    ),
    "model-output.synthetic-citation-failure.001": (
        "1.0.0",
        "synthetic_citation_failure_v1.json",
        "citation-failure",
    ),
    "model-output.synthetic-malformed.001": (
        "1.0.0",
        "synthetic_malformed_output_v1.json",
        "malformed-output",
    ),
}
MODEL_OUTPUT_LICENSE_REF = "fixture:synthetic-model-outputs"


# PyYAML does not expose SafeLoader typing to mypy.
class DuplicateKeySafeLoader(yaml.SafeLoader):  # type: ignore[misc]
    """Safe YAML loader that rejects ambiguous mappings."""


def construct_mapping_without_duplicate_fields(
    loader: DuplicateKeySafeLoader,
    node: Any,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    value: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        field_name = loader.construct_object(key_node, deep=deep)
        if field_name in value:
            raise ValueError(f"duplicate YAML field {field_name!r}")
        value[field_name] = loader.construct_object(value_node, deep=deep)
    return value


DuplicateKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_mapping_without_duplicate_fields,
)


def load_json(path: Path) -> dict[str, Any]:
    def object_without_duplicate_fields(
        pairs: list[tuple[str, Any]],
    ) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for field_name, field_value in pairs:
            if field_name in value:
                raise ValueError(f"{path}: duplicate JSON field {field_name!r}")
            value[field_name] = field_value
        return value

    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=object_without_duplicate_fields,
    )
    if not isinstance(value, dict):
        raise ValueError(f"{path}: top-level value must be an object")
    return value


def require_fields(value: dict[str, Any], fields: set[str], path: Path) -> None:
    missing = fields - set(value)
    if missing:
        raise ValueError(f"{path}: missing fields {sorted(missing)}")


def content_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def is_utf8_encodable(value: str) -> bool:
    """Return whether a JSON string can safely be stored in SQLite text."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def resolve_fixture_path(
    manifest_path: Path,
    raw_path: object,
    *,
    fixture_root: Path | None = None,
) -> Path:
    if not isinstance(raw_path, str) or Path(raw_path).is_absolute():
        raise ValueError(f"{manifest_path}: fixture paths must be relative")
    root = fixture_root or ROOT
    try:
        fixture_path = (root / raw_path).resolve(strict=True)
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
    *,
    fixture_root: Path | None = None,
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
        fixture_path = resolve_fixture_path(
            path,
            entry["path"],
            fixture_root=fixture_root,
        )
        if fixture_path in referenced_paths:
            raise ValueError(f"{path}: fixture paths must reference unique files")
        referenced_paths.add(fixture_path)
        if entry["content_hash"] != content_hash(fixture_path):
            raise ValueError(f"{path}: stale content hash for {entry['path']}")
        license_ref = entry["license_ref"]
        if (
            not isinstance(license_ref, str)
            or not license_ref
            or license_ref != license_ref.strip()
        ):
            raise ValueError(
                f"{path}: license references must be non-empty, trimmed strings"
            )
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

    excluded_files = {path.absolute(), (path.parent / "README.md").absolute()}
    fixture_files = {
        candidate.absolute()
        for candidate in path.parent.rglob("*")
        if (candidate.is_file() or candidate.is_symlink())
        and candidate.absolute() not in excluded_files
    }
    if fixture_files != referenced_paths:
        raise ValueError(
            f"{path}: all fixture files must be registered in the manifest"
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

    seen_document_ids: set[str] = set()
    for record in records:
        fixture_path = resolve_fixture_path(path, record["path"])
        try:
            payload = load_json(fixture_path)
            if set(payload) != CORPUS_PAYLOAD_FIELDS:
                raise ValueError("corpus payload fields do not match the schema")
            if payload["synthetic"] is not True:
                raise ValueError("corpus payload must be synthetic")
            document_id = payload["document_id"]
            if (
                not isinstance(document_id, str)
                or not document_id
                or document_id != document_id.strip()
                or document_id in seen_document_ids
                or not is_utf8_encodable(document_id)
            ):
                raise ValueError(
                    "corpus payload document IDs must be unique non-empty, "
                    "trimmed strings"
                )
            seen_document_ids.add(document_id)
            for field_name in ("title", "text"):
                field_value = payload[field_name]
                if (
                    not isinstance(field_value, str)
                    or not field_value.strip()
                    or "\x00" in field_value
                    or not is_utf8_encodable(field_value)
                ):
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
            payload = load_json(fixture_path)
            SyntheticRequestContext.from_json(json.dumps(payload))
        except (OSError, TypeError, ValueError) as error:
            raise ValueError(
                f"{fixture_path}: invalid synthetic request context"
            ) from error


def validate_model_output_fixture(
    path: Path, registry: dict[str, dict[str, Any]]
) -> None:
    """Validate the exact controlled DSL-110 model-output scenarios."""
    manifest = load_json(path)
    fixture_ids = validate_manifest(
        path,
        registry,
        "fixtures",
        fixture_root=path.parent,
    )
    if fixture_ids != set(MODEL_OUTPUT_FIXTURES):
        raise ValueError(
            "model-output manifest must contain exactly the approved scenarios"
        )
    license_entry = registry.get(MODEL_OUTPUT_LICENSE_REF)
    if (
        license_entry is None
        or license_entry.get("source") != "Repository-authored fixture"
        or license_entry.get("permitted_use_basis")
        != "Repository-authored synthetic content."
    ):
        raise ValueError(
            "model-output fixtures must use the repository-authored synthetic "
            "license/source entry"
        )
    entries = manifest.get("fixtures")
    if not isinstance(entries, list):
        raise ValueError(f"{path}: model-output manifest must contain fixtures")

    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: model-output manifest entries must be objects")
        fixture_id = entry.get("id")
        if not isinstance(fixture_id, str) or fixture_id not in MODEL_OUTPUT_FIXTURES:
            raise ValueError(f"{path}: unsupported model-output fixture")
        expected_version, expected_path, scenario = MODEL_OUTPUT_FIXTURES[fixture_id]
        if (
            entry.get("version") != expected_version
            or entry.get("path") != expected_path
            or entry.get("license_ref") != MODEL_OUTPUT_LICENSE_REF
        ):
            raise ValueError(
                f"{path}: model-output fixture metadata does not match the "
                f"{scenario} scenario"
            )

        fixture_path = resolve_fixture_path(
            path,
            entry["path"],
            fixture_root=path.parent,
        )
        output_json = fixture_path.read_text(encoding="utf-8")
        if scenario == "malformed-output":
            payload = load_json(fixture_path)
            raw_citations = payload.get("citations")
            if (
                set(payload) != {"answer_text", "citations"}
                or not isinstance(payload.get("answer_text"), str)
                or not payload["answer_text"].strip()
                or not isinstance(raw_citations, list)
                or len(raw_citations) != 1
                or not isinstance(raw_citations[0], dict)
                or raw_citations[0] != {"source_id": "synthetic-source-001"}
            ):
                raise ValueError(
                    f"{fixture_path}: malformed-output fixture must contain the "
                    "approved missing-chunk_id failure"
                )
            try:
                ResearchResult.from_json(output_json)
            except ValueError as error:
                if str(error) != "citation fields do not match the contract":
                    raise ValueError(
                        f"{fixture_path}: malformed-output fixture failed in an "
                        "unexpected way"
                    ) from error
            else:
                raise ValueError(
                    f"{fixture_path}: malformed-output fixture must remain malformed"
                )
            continue

        try:
            result = ResearchResult.from_json(output_json)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"{fixture_path}: invalid structured model-output fixture"
            ) from error
        if scenario == "happy-path" and result.citations != (
            CitationReference("synthetic-source-001", "synthetic-chunk-001"),
            CitationReference("synthetic-source-002", "synthetic-chunk-002"),
        ):
            raise ValueError(
                f"{fixture_path}: happy-path fixture citations do not match "
                "the approved scenario"
            )
        if scenario == "citation-failure" and result.citations != (
            CitationReference(
                "synthetic-source-not-supplied",
                "synthetic-chunk-not-supplied",
            ),
        ):
            raise ValueError(
                f"{fixture_path}: citation-failure fixture does not contain "
                "the approved unsupported reference"
            )


def validate_fixture_inventory(manifests: set[Path]) -> None:
    """Reject fixture content outside directories with dedicated validation."""
    fixture_root = ROOT / "fixtures"
    fixture_files = {
        candidate.absolute()
        for candidate in fixture_root.rglob("*")
        if candidate.is_file() or candidate.is_symlink()
    }
    managed_directories = {manifest.parent.absolute() for manifest in manifests}
    documentation_files = {
        (ROOT / relative_path).absolute()
        for relative_path in FIXTURE_DOCUMENTATION_PATHS
    }
    unmanaged_files = {
        fixture_file
        for fixture_file in fixture_files - documentation_files
        if not any(
            fixture_file.is_relative_to(directory) for directory in managed_directories
        )
    }
    if unmanaged_files:
        relative_paths = sorted(
            path.relative_to(ROOT.absolute()).as_posix() for path in unmanaged_files
        )
        raise ValueError(
            f"fixture files outside validated manifest directories: {relative_paths}"
        )


def validate() -> None:
    registry_value = yaml.load(
        (ROOT / "licenses/registry.yaml").read_text(encoding="utf-8"),
        Loader=DuplicateKeySafeLoader,
    )
    if not isinstance(registry_value, list):
        raise ValueError("licenses/registry.yaml must contain a list")
    registry: dict[str, dict[str, Any]] = {}
    for entry in registry_value:
        if not isinstance(entry, dict):
            raise ValueError("license registry entries must be objects")
        registry_id = entry.get("id")
        if (
            not isinstance(registry_id, str)
            or not registry_id
            or registry_id != registry_id.strip()
        ):
            raise ValueError("license registry IDs must be non-empty, trimmed strings")
        if registry_id in registry:
            raise ValueError("license registry IDs must be unique")
        registry[registry_id] = entry
    manifest_validators = {
        ROOT / "fixtures/contexts/manifest.json": validate_context_fixture,
        ROOT / "fixtures/permissions/manifest.json": validate_permission_fixture,
        ROOT / "fixtures/corpus/manifest.json": validate_corpus,
        ROOT
        / "src/privilab/adapters/models/resources/governed_fixtures/manifest.json": (
            validate_model_output_fixture
        ),
    }
    for manifest, validator in manifest_validators.items():
        validator(manifest, registry)
    validate_fixture_inventory(set(manifest_validators))


if __name__ == "__main__":
    try:
        validate()
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as error:
        print(f"fixture validation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print("fixture validation passed")
