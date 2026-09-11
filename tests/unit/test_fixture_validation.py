from __future__ import annotations

import importlib.util
import json
import shutil
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


def test_manifest_dispatch_is_independent_of_checkout_ancestor_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "corpus/privilab"
    licenses = repository / "licenses"
    licenses.mkdir(parents=True)
    (licenses / "registry.yaml").write_text("[]", encoding="utf-8")
    manifests = (
        repository / "fixtures/contexts/manifest.json",
        repository / "fixtures/permissions/manifest.json",
        repository / "fixtures/corpus/manifest.json",
        repository / "fixtures/model_outputs/manifest.json",
    )
    calls: list[tuple[str, Path]] = []

    def record_context(path: Path, _registry: object) -> None:
        calls.append(("context", path))

    def record_permission(path: Path, _registry: object) -> None:
        calls.append(("permission", path))

    def record_corpus(path: Path, _registry: object) -> None:
        calls.append(("corpus", path))

    def record_model_output(path: Path, _registry: object) -> None:
        calls.append(("model-output", path))

    monkeypatch.setattr(VALIDATOR, "ROOT", repository)
    monkeypatch.setattr(VALIDATOR, "validate_context_fixture", record_context)
    monkeypatch.setattr(VALIDATOR, "validate_permission_fixture", record_permission)
    monkeypatch.setattr(VALIDATOR, "validate_corpus", record_corpus)
    monkeypatch.setattr(VALIDATOR, "validate_model_output_fixture", record_model_output)

    VALIDATOR.validate()

    assert calls == [
        ("context", manifests[0]),
        ("permission", manifests[1]),
        ("corpus", manifests[2]),
        ("model-output", manifests[3]),
    ]


@pytest.mark.parametrize(
    "relative_path",
    [
        "fixtures/new_fixture_kind/unregistered.txt",
    ],
)
def test_validate_rejects_files_outside_manifest_managed_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
) -> None:
    repository = tmp_path / "repository"
    licenses = repository / "licenses"
    licenses.mkdir(parents=True)
    (licenses / "registry.yaml").write_text("[]", encoding="utf-8")
    unregistered = repository / relative_path
    unregistered.parent.mkdir(parents=True)
    unregistered.write_text("unregistered fixture content", encoding="utf-8")

    def accept_manifest(_path: Path, _registry: object) -> None:
        pass

    monkeypatch.setattr(VALIDATOR, "ROOT", repository)
    monkeypatch.setattr(VALIDATOR, "validate_context_fixture", accept_manifest)
    monkeypatch.setattr(VALIDATOR, "validate_permission_fixture", accept_manifest)
    monkeypatch.setattr(VALIDATOR, "validate_corpus", accept_manifest)
    monkeypatch.setattr(VALIDATOR, "validate_model_output_fixture", accept_manifest)

    with pytest.raises(ValueError, match="outside validated manifest directories"):
        VALIDATOR.validate()


def test_validate_allows_explicit_fixture_documentation_placeholders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    licenses = repository / "licenses"
    licenses.mkdir(parents=True)
    (licenses / "registry.yaml").write_text("[]", encoding="utf-8")
    for relative_path in VALIDATOR.FIXTURE_DOCUMENTATION_PATHS:
        documentation = repository / relative_path
        documentation.parent.mkdir(parents=True, exist_ok=True)
        documentation.write_text("Fixture documentation.", encoding="utf-8")

    def accept_manifest(_path: Path, _registry: object) -> None:
        pass

    monkeypatch.setattr(VALIDATOR, "ROOT", repository)
    monkeypatch.setattr(VALIDATOR, "validate_context_fixture", accept_manifest)
    monkeypatch.setattr(VALIDATOR, "validate_permission_fixture", accept_manifest)
    monkeypatch.setattr(VALIDATOR, "validate_corpus", accept_manifest)
    monkeypatch.setattr(VALIDATOR, "validate_model_output_fixture", accept_manifest)

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
    license_ref: object,
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


def write_model_output_fixture_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    repository = tmp_path / "repository"
    fixture_dir = repository / "fixtures/model_outputs"
    shutil.copytree(ROOT / "fixtures/model_outputs", fixture_dir)
    monkeypatch.setattr(VALIDATOR, "ROOT", repository)
    return fixture_dir / "manifest.json"


def model_output_registry() -> dict[str, dict[str, object]]:
    test_registry = registry()
    test_registry["fixture:synthetic-model-outputs"] = {
        **test_registry["fixture:synthetic-model-outputs"],
        "repository_paths": [
            "fixtures/model_outputs/manifest.json",
            "fixtures/model_outputs/synthetic_happy_path_v1.json",
            "fixtures/model_outputs/synthetic_citation_failure_v1.json",
            "fixtures/model_outputs/synthetic_malformed_output_v1.json",
        ],
    }
    return test_registry


def update_manifested_fixture_hash(manifest: Path, fixture_id: str) -> None:
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    entry = next(
        item for item in manifest_payload["fixtures"] if item["id"] == fixture_id
    )
    fixture_path = VALIDATOR.ROOT / entry["path"]
    entry["content_hash"] = VALIDATOR.content_hash(fixture_path)
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")


def test_unknown_license_reference_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_context_manifest(
        tmp_path, monkeypatch, license_ref="license:missing"
    )

    with pytest.raises(ValueError, match="unknown license reference"):
        VALIDATOR.validate_manifest(manifest, registry(), "fixtures")


@pytest.mark.parametrize(
    "license_ref",
    [True, "", " ", " fixture:synthetic-contexts "],
)
def test_manifest_license_references_require_non_empty_trimmed_strings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    license_ref: object,
) -> None:
    manifest = write_context_manifest(tmp_path, monkeypatch, license_ref=license_ref)

    with pytest.raises(ValueError, match="non-empty, trimmed strings"):
        VALIDATOR.validate_manifest(manifest, registry(), "fixtures")


@pytest.mark.parametrize(
    "registry_id",
    [True, "", " ", " fixture:synthetic-contexts "],
)
def test_license_registry_ids_require_non_empty_trimmed_strings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry_id: object,
) -> None:
    repository = tmp_path / "repository"
    licenses = repository / "licenses"
    licenses.mkdir(parents=True)
    (licenses / "registry.yaml").write_text(
        yaml.safe_dump([{"id": registry_id}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(VALIDATOR, "ROOT", repository)

    with pytest.raises(ValueError, match="non-empty, trimmed strings"):
        VALIDATOR.validate()


@pytest.mark.parametrize(
    "registry_entry",
    [
        '- id: false\n  id: "fixture:synthetic-contexts"',
        '- id: "fixture:synthetic-contexts"\n  kind: dependency\n  kind: fixture',
        (
            '- id: "fixture:synthetic-contexts"\n'
            "  permitted_use_basis: false\n"
            '  permitted_use_basis: "Repository-authored synthetic content."'
        ),
    ],
)
def test_license_registry_rejects_duplicate_yaml_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry_entry: str,
) -> None:
    repository = tmp_path / "repository"
    licenses = repository / "licenses"
    licenses.mkdir(parents=True)
    (licenses / "registry.yaml").write_text(registry_entry, encoding="utf-8")
    monkeypatch.setattr(VALIDATOR, "ROOT", repository)

    with pytest.raises(ValueError, match="duplicate YAML field"):
        VALIDATOR.validate()


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


def test_manifest_rejects_duplicate_json_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_context_manifest(
        tmp_path, monkeypatch, license_ref="fixture:synthetic-contexts"
    )
    manifest_text = manifest.read_text(encoding="utf-8").replace(
        '"schema_version": "1"',
        '"schema_version": "0", "schema_version": "1"',
        1,
    )
    manifest.write_text(manifest_text, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON field 'schema_version'"):
        VALIDATOR.validate_context_fixture(manifest, registry())


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
@pytest.mark.parametrize(
    "manifest_kind", ["context", "permission", "corpus", "model-output"]
)
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
    elif manifest_kind == "corpus":
        manifest = write_corpus_manifest(tmp_path, monkeypatch)
        collection_key = "records"
        test_registry = corpus_registry()
        validator = VALIDATOR.validate_corpus
    else:
        manifest = write_model_output_fixture_tree(tmp_path, monkeypatch)
        collection_key = "fixtures"
        test_registry = model_output_registry()
        validator = VALIDATOR.validate_model_output_fixture

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


def test_context_payload_rejects_duplicate_json_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_context_manifest(
        tmp_path, monkeypatch, license_ref="fixture:synthetic-contexts"
    )
    fixture_path = manifest.parent / "synthetic_request_context_v1.json"
    fixture_text = fixture_path.read_text(encoding="utf-8").replace(
        '"synthetic": true',
        '"synthetic": false,\n  "synthetic": true',
        1,
    )
    fixture_path.write_text(fixture_text, encoding="utf-8")
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


@pytest.mark.parametrize("field_name", ["title", "text"])
def test_corpus_payload_text_fields_reject_nul_characters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field_name: str
) -> None:
    manifest = write_corpus_manifest(tmp_path, monkeypatch)
    fixture_path = manifest.parent / "synthetic_trade_notice_v1.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    payload[field_name] = f"synthetic\x00{field_name}"
    fixture_path.write_text(json.dumps(payload), encoding="utf-8")
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["records"][0]["content_hash"] = VALIDATOR.content_hash(
        fixture_path
    )
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid synthetic corpus payload"):
        VALIDATOR.validate_corpus(manifest, corpus_registry())


@pytest.mark.parametrize("field_name", ["document_id", "title", "text"])
def test_corpus_payload_rejects_lone_surrogates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field_name: str
) -> None:
    manifest = write_corpus_manifest(tmp_path, monkeypatch)
    fixture_path = manifest.parent / "synthetic_trade_notice_v1.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    payload[field_name] = "synthetic\ud800value"
    fixture_path.write_text(json.dumps(payload), encoding="utf-8")
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["records"][0]["content_hash"] = VALIDATOR.content_hash(
        fixture_path
    )
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid synthetic corpus payload"):
        VALIDATOR.validate_corpus(manifest, corpus_registry())


@pytest.mark.parametrize(
    "second_document_id",
    [
        "synthetic-trade-notice-001",
        " synthetic-trade-notice-001 ",
    ],
)
def test_corpus_document_ids_require_unique_trimmed_strings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    second_document_id: str,
) -> None:
    manifest = write_corpus_manifest(tmp_path, monkeypatch)
    first_fixture = manifest.parent / "synthetic_trade_notice_v1.json"
    second_fixture = manifest.parent / "synthetic_trade_notice_v2.json"
    second_payload = json.loads(first_fixture.read_text(encoding="utf-8"))
    second_payload["document_id"] = second_document_id
    second_fixture.write_text(json.dumps(second_payload), encoding="utf-8")

    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    second_record = {
        **manifest_payload["records"][0],
        "id": "corpus.synthetic.002",
        "path": "fixtures/corpus/synthetic_trade_notice_v2.json",
        "content_hash": VALIDATOR.content_hash(second_fixture),
    }
    manifest_payload["records"].append(second_record)
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    test_registry = corpus_registry()
    test_registry["fixture:synthetic-corpus"] = {
        **test_registry["fixture:synthetic-corpus"],
        "repository_paths": [
            "fixtures/corpus/manifest.json",
            "fixtures/corpus/synthetic_trade_notice_v1.json",
            "fixtures/corpus/synthetic_trade_notice_v2.json",
        ],
    }

    with pytest.raises(ValueError, match="invalid synthetic corpus payload") as error:
        VALIDATOR.validate_corpus(manifest, test_registry)
    assert error.value.__cause__ is not None
    assert "unique non-empty, trimmed strings" in str(error.value.__cause__)


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


def test_permission_payload_rejects_duplicate_json_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = json.loads(
        (ROOT / "fixtures/permissions/synthetic_permission_results_v1.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = write_permission_manifest(tmp_path, monkeypatch, payload)
    fixture_path = manifest.parent / "selected_permission_results.json"
    fixture_text = fixture_path.read_text(encoding="utf-8").replace(
        '"synthetic": true',
        '"synthetic": false, "synthetic": true',
        1,
    )
    fixture_path.write_text(fixture_text, encoding="utf-8")
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["fixtures"][0]["content_hash"] = VALIDATOR.content_hash(
        fixture_path
    )
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON field 'synthetic'"):
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


def test_controlled_model_output_scenarios_validate() -> None:
    VALIDATOR.validate_model_output_fixture(
        ROOT / "fixtures/model_outputs/manifest.json",
        model_output_registry(),
    )


@pytest.mark.parametrize(
    ("field_name", "field_value", "message"),
    [
        ("synthetic", False, "must be synthetic"),
        ("license_ref", "fixture:missing", "unknown license reference"),
        ("content_hash", "sha256:" + "0" * 64, "stale content hash"),
    ],
)
def test_model_output_fixtures_retain_generic_manifest_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    field_value: object,
    message: str,
) -> None:
    manifest = write_model_output_fixture_tree(tmp_path, monkeypatch)
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["fixtures"][0][field_name] = field_value
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        VALIDATOR.validate_model_output_fixture(manifest, model_output_registry())


def test_model_output_manifest_requires_the_exact_approved_scenarios(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_model_output_fixture_tree(tmp_path, monkeypatch)
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["fixtures"][0]["id"] = "model-output.synthetic-unknown.001"
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly the approved scenarios"):
        VALIDATOR.validate_model_output_fixture(manifest, model_output_registry())


def test_model_output_validator_rejects_arbitrary_malformed_shapes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_model_output_fixture_tree(tmp_path, monkeypatch)
    fixture_path = (
        VALIDATOR.ROOT / "fixtures/model_outputs/synthetic_malformed_output_v1.json"
    )
    fixture_path.write_text(
        json.dumps(
            {
                "answer_text": "A different malformed synthetic output.",
                "citations": [],
            }
        ),
        encoding="utf-8",
    )
    update_manifested_fixture_hash(manifest, "model-output.synthetic-malformed.001")

    with pytest.raises(ValueError, match="approved missing-chunk_id failure"):
        VALIDATOR.validate_model_output_fixture(manifest, model_output_registry())


def test_deliberately_malformed_model_output_cannot_be_replaced_by_a_valid_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_model_output_fixture_tree(tmp_path, monkeypatch)
    fixture_path = (
        VALIDATOR.ROOT / "fixtures/model_outputs/synthetic_malformed_output_v1.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    payload["citations"][0]["chunk_id"] = "synthetic-chunk-001"
    fixture_path.write_text(json.dumps(payload), encoding="utf-8")
    update_manifested_fixture_hash(manifest, "model-output.synthetic-malformed.001")

    with pytest.raises(ValueError, match="approved missing-chunk_id failure"):
        VALIDATOR.validate_model_output_fixture(manifest, model_output_registry())


def test_unregistered_model_output_fixture_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_model_output_fixture_tree(tmp_path, monkeypatch)
    (manifest.parent / "unregistered.json").write_text(
        '{"answer_text":"Unregistered.","citations":[]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be registered in the manifest"):
        VALIDATOR.validate_model_output_fixture(manifest, model_output_registry())
