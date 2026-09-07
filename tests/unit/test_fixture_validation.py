from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MODULE_SPEC = importlib.util.spec_from_file_location(
    "validate_fixtures", ROOT / "scripts/validate_fixtures.py"
)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(VALIDATOR)


def registry() -> dict[str, dict[str, object]]:
    entries = yaml.safe_load(
        (ROOT / "licenses/registry.yaml").read_text(encoding="utf-8")
    )
    return {entry["id"]: entry for entry in entries}


def test_dsl106_fixture_substrate_validates() -> None:
    VALIDATOR.validate()


def test_fixture_hash_is_reproducible() -> None:
    fixture = ROOT / "fixtures/contexts/synthetic_request_context_v1.json"

    assert VALIDATOR.content_hash(fixture) == (
        "sha256:e2ff7417d2960f9a3abb18cb93949b609bd3797043af93e80aebc6dede821182"
    )


def write_context_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    license_ref: str,
    content_hash: str | None = None,
) -> Path:
    repository = tmp_path / "repository"
    fixture_dir = repository / "fixtures/contexts"
    fixture_dir.mkdir(parents=True)
    fixture = fixture_dir / "synthetic_request_context_v1.json"
    fixture.write_bytes(
        (ROOT / "fixtures/contexts/synthetic_request_context_v1.json").read_bytes()
    )
    monkeypatch.setattr(VALIDATOR, "ROOT", repository)
    manifest = fixture_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "fixtures": [
                    {
                        "id": "fixture.unknown-license.001",
                        "version": "1.0.0",
                        "path": "fixtures/contexts/synthetic_request_context_v1.json",
                        "content_hash": content_hash or VALIDATOR.content_hash(fixture),
                        "synthetic": True,
                        "license_ref": license_ref,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def write_corpus_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repository = tmp_path / "repository"
    fixture_dir = repository / "fixtures/corpus"
    fixture_dir.mkdir(parents=True)
    fixture = fixture_dir / "synthetic_trade_notice_v1.json"
    fixture.write_bytes(
        (ROOT / "fixtures/corpus/synthetic_trade_notice_v1.json").read_bytes()
    )
    monkeypatch.setattr(VALIDATOR, "ROOT", repository)
    manifest = fixture_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "records": [
                    {
                        "id": "corpus.synthetic.001",
                        "version": "1.0.0",
                        "path": "fixtures/corpus/synthetic_trade_notice_v1.json",
                        "content_hash": VALIDATOR.content_hash(fixture),
                        "synthetic": True,
                        "origin": "Repository-authored synthetic fixture.",
                        "permitted_use_basis": "Repository-authored synthetic content.",
                        "license_ref": "fixture:synthetic-corpus",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def corpus_registry() -> dict[str, dict[str, object]]:
    test_registry = registry()
    test_registry["fixture:synthetic-corpus"] = {
        **test_registry["fixture:synthetic-corpus"],
        "repository_paths": [
            "fixtures/corpus/manifest.json",
            "fixtures/corpus/synthetic_trade_notice_v1.json",
        ],
    }
    return test_registry


def write_permission_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> Path:
    repository = tmp_path / "repository"
    fixture_dir = repository / "fixtures/permissions"
    fixture_dir.mkdir(parents=True)
    payload_path = fixture_dir / "selected_permission_results.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    manifest = fixture_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "fixtures": [
                    {
                        "id": "permission-results.selected.001",
                        "version": "1.0.0",
                        "path": "fixtures/permissions/selected_permission_results.json",
                        "content_hash": VALIDATOR.content_hash(payload_path),
                        "synthetic": True,
                        "license_ref": "fixture:synthetic-permissions",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(VALIDATOR, "ROOT", repository)
    return manifest


def permission_registry() -> dict[str, dict[str, object]]:
    test_registry = registry()
    test_registry["fixture:synthetic-permissions"] = {
        **test_registry["fixture:synthetic-permissions"],
        "repository_paths": [
            "fixtures/permissions/manifest.json",
            "fixtures/permissions/selected_permission_results.json",
        ],
    }
    return test_registry


def test_unknown_license_reference_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_context_manifest(
        tmp_path, monkeypatch, license_ref="license:missing"
    )

    with pytest.raises(ValueError, match="unknown license reference"):
        VALIDATOR.validate_manifest(manifest, registry(), "fixtures")


def test_stale_fixture_hash_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_context_manifest(
        tmp_path,
        monkeypatch,
        license_ref="fixture:synthetic-contexts",
        content_hash="sha256:" + "0" * 64,
    )

    with pytest.raises(ValueError, match="stale content hash"):
        VALIDATOR.validate_manifest(manifest, registry(), "fixtures")


def test_fixture_path_cannot_escape_its_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_context_manifest(
        tmp_path, monkeypatch, license_ref="fixture:synthetic-contexts"
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["fixtures"][0]["path"] = "../outside.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="inside its fixture directory"):
        VALIDATOR.validate_manifest(manifest, registry(), "fixtures")


def test_unmanifested_fixture_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_context_manifest(
        tmp_path, monkeypatch, license_ref="fixture:synthetic-contexts"
    )
    unregistered = manifest.parent / "unregistered.json"
    unregistered.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="must be registered in the manifest"):
        VALIDATOR.validate_manifest(manifest, registry(), "fixtures")


def test_nested_manifest_named_json_file_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_corpus_manifest(tmp_path, monkeypatch)
    nested_manifest = manifest.parent / "archive/manifest.json"
    nested_manifest.parent.mkdir()
    nested_manifest.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="must be registered in the manifest"):
        VALIDATOR.validate_corpus(manifest, corpus_registry())


@pytest.mark.parametrize(
    "relative_path",
    ["unregistered.txt", "unregistered.csv", "unregistered.JSON"],
)
def test_unregistered_fixture_file_extensions_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative_path: str
) -> None:
    manifest = write_corpus_manifest(tmp_path, monkeypatch)
    unregistered = manifest.parent / relative_path
    unregistered.write_text("synthetic unregistered content", encoding="utf-8")

    with pytest.raises(ValueError, match="all fixture files must be registered"):
        VALIDATOR.validate_corpus(manifest, corpus_registry())


def test_unregistered_symlink_alias_does_not_collapse_onto_registered_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_corpus_manifest(tmp_path, monkeypatch)
    alias = manifest.parent / "payload-alias.json"
    alias.symlink_to("synthetic_trade_notice_v1.json")

    with pytest.raises(ValueError, match="all fixture files must be registered"):
        VALIDATOR.validate_corpus(manifest, corpus_registry())


def test_unregistered_directory_symlink_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_corpus_manifest(tmp_path, monkeypatch)
    target = tmp_path / "unscanned-fixtures"
    target.mkdir()
    alias = manifest.parent / "fixture-directory-alias"
    alias.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="all fixture files must be registered"):
        VALIDATOR.validate_corpus(manifest, corpus_registry())


def test_manifest_entries_cannot_share_a_resolved_fixture_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_context_manifest(
        tmp_path, monkeypatch, license_ref="fixture:synthetic-contexts"
    )
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    duplicate = {
        **manifest_payload["fixtures"][0],
        "id": "fixture.duplicate-path.002",
        "version": "2.0.0",
    }
    manifest_payload["fixtures"].append(duplicate)
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="paths must reference unique files"):
        VALIDATOR.validate_manifest(manifest, registry(), "fixtures")


def test_license_reference_must_cover_fixture_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_context_manifest(
        tmp_path, monkeypatch, license_ref="pypi:annotated-doc"
    )

    with pytest.raises(ValueError, match="does not cover fixture"):
        VALIDATOR.validate_manifest(manifest, registry(), "fixtures")


def test_license_registry_version_must_match_manifest_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_context_manifest(
        tmp_path, monkeypatch, license_ref="fixture:synthetic-contexts"
    )
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["fixtures"][0]["version"] = "2.0.0"
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="registry version .* does not match manifest"):
        VALIDATOR.validate_manifest(manifest, registry(), "fixtures")


@pytest.mark.parametrize(
    ("schema_level", "message"),
    [
        ("manifest", "manifest fields do not match the schema"),
        ("entry", "entry fields do not match the schema"),
    ],
)
@pytest.mark.parametrize("manifest_kind", ["context", "permission", "corpus"])
def test_manifest_schemas_reject_undeclared_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manifest_kind: str,
    schema_level: str,
    message: str,
) -> None:
    if manifest_kind == "context":
        manifest = write_context_manifest(
            tmp_path, monkeypatch, license_ref="fixture:synthetic-contexts"
        )
        collection_key = "fixtures"
        test_registry = registry()
        validator = VALIDATOR.validate_context_fixture
    elif manifest_kind == "permission":
        permission_payload = json.loads(
            (
                ROOT / "fixtures/permissions/synthetic_permission_results_v1.json"
            ).read_text(encoding="utf-8")
        )
        manifest = write_permission_manifest(tmp_path, monkeypatch, permission_payload)
        collection_key = "fixtures"
        test_registry = permission_registry()
        validator = VALIDATOR.validate_permission_fixture
    else:
        manifest = write_corpus_manifest(tmp_path, monkeypatch)
        collection_key = "records"
        test_registry = corpus_registry()
        validator = VALIDATOR.validate_corpus

    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    if schema_level == "manifest":
        manifest_payload["unexpected"] = "schema drift"
    else:
        manifest_payload[collection_key][0]["unexpected"] = "schema drift"
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        validator(manifest, test_registry)


@pytest.mark.parametrize(
    ("field_name", "field_value", "message"),
    [
        ("id", " ", "fixture IDs must be unique non-empty, trimmed strings"),
        (
            "id",
            " context.synthetic.001 ",
            "fixture IDs must be unique non-empty, trimmed strings",
        ),
        ("version", "\t", "fixture versions must be non-empty, trimmed strings"),
        (
            "version",
            " 1.0.0 ",
            "fixture versions must be non-empty, trimmed strings",
        ),
    ],
)
def test_manifest_ids_and_versions_require_non_empty_trimmed_strings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    field_value: str,
    message: str,
) -> None:
    manifest = write_context_manifest(
        tmp_path, monkeypatch, license_ref="fixture:synthetic-contexts"
    )
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["fixtures"][0][field_name] = field_value
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        VALIDATOR.validate_manifest(manifest, registry(), "fixtures")


def test_corpus_manifest_rejects_shadow_fixtures_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_corpus_manifest(tmp_path, monkeypatch)
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    record = manifest_payload["records"][0]
    manifest_payload["fixtures"] = [record.copy()]
    record.pop("id")
    record.pop("version")
    record["content_hash"] = "sha256:" + "0" * 64
    record["synthetic"] = False
    record["license_ref"] = "license:missing"
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="only the records collection"):
        VALIDATOR.validate_corpus(manifest, corpus_registry())


@pytest.mark.parametrize(
    "context_payload",
    [
        {"client": None, "matter": None, "user": None, "workflow": None},
        {
            "client": {"client_id": False},
            "matter": None,
            "synthetic": True,
            "user": None,
            "workflow": None,
        },
        {
            "client": None,
            "matter": None,
            "synthetic": False,
            "user": None,
            "workflow": None,
        },
    ],
)
def test_context_validation_parses_manifest_selected_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, context_payload: dict[str, object]
) -> None:
    manifest = write_context_manifest(
        tmp_path, monkeypatch, license_ref="fixture:synthetic-contexts"
    )
    fixture_path = manifest.parent / "synthetic_request_context_v1.json"
    fixture_path.write_text(json.dumps(context_payload), encoding="utf-8")
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["fixtures"][0]["content_hash"] = VALIDATOR.content_hash(
        fixture_path
    )
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid synthetic request context"):
        VALIDATOR.validate_context_fixture(manifest, registry())


@pytest.mark.parametrize(
    "corpus_payload",
    [
        "not valid JSON",
        json.dumps(
            {
                "document_id": "synthetic-document-001",
                "title": "Synthetic document",
                "text": "Synthetic content.",
                "synthetic": False,
            }
        ),
        json.dumps(
            {
                "document_id": "synthetic-document-001",
                "title": "Synthetic document",
                "synthetic": True,
            }
        ),
    ],
)
def test_corpus_validation_parses_manifest_selected_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corpus_payload: str
) -> None:
    manifest = write_corpus_manifest(tmp_path, monkeypatch)
    fixture_path = manifest.parent / "synthetic_trade_notice_v1.json"
    fixture_path.write_text(corpus_payload, encoding="utf-8")
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["records"][0]["content_hash"] = VALIDATOR.content_hash(
        fixture_path
    )
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid synthetic corpus payload"):
        VALIDATOR.validate_corpus(manifest, corpus_registry())


@pytest.mark.parametrize("field_name", ["document_id", "title", "text"])
def test_corpus_payload_text_fields_reject_whitespace_only_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field_name: str
) -> None:
    manifest = write_corpus_manifest(tmp_path, monkeypatch)
    fixture_path = manifest.parent / "synthetic_trade_notice_v1.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    payload[field_name] = " \t\n"
    fixture_path.write_text(json.dumps(payload), encoding="utf-8")
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["records"][0]["content_hash"] = VALIDATOR.content_hash(
        fixture_path
    )
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid synthetic corpus payload"):
        VALIDATOR.validate_corpus(manifest, corpus_registry())


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("origin", True),
        ("permitted_use_basis", ["unknown"]),
        ("origin", "  Repository-authored synthetic fixture."),
        ("permitted_use_basis", "   "),
    ],
)
def test_corpus_provenance_requires_non_empty_trimmed_strings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    field_value: object,
) -> None:
    manifest = write_corpus_manifest(tmp_path, monkeypatch)
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["records"][0][field_name] = field_value
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty, trimmed strings"):
        VALIDATOR.validate_corpus(manifest, corpus_registry())


def test_permission_validation_uses_manifest_selected_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_permission_manifest(
        tmp_path,
        monkeypatch,
        {
            "fixtures": [{"condition_ids": [], "state": "ALLOW"}],
            "synthetic": True,
        },
    )

    with pytest.raises(ValueError, match="must cover exactly the approved states"):
        VALIDATOR.validate_permission_fixture(manifest, permission_registry())


def test_permission_payload_rejects_unexpected_envelope_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = json.loads(
        (ROOT / "fixtures/permissions/synthetic_permission_results_v1.json").read_text(
            encoding="utf-8"
        )
    )
    payload["unexpected"] = "schema drift"
    manifest = write_permission_manifest(tmp_path, monkeypatch, payload)

    with pytest.raises(ValueError, match="fields do not match the schema"):
        VALIDATOR.validate_permission_fixture(manifest, permission_registry())
