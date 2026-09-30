"""Reject ambiguous, inconsistent, or unregistered outer task artifacts."""

from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from privilab.application.trade_regulatory_tasks import (
    GOLDEN_PATH,
    PACK_PATH,
    SCENARIOS,
    TASK_CHOICES,
    TASK_FIELDS,
    VERSION,
    load_task_pack,
    parse_expected,
)

ROOT = Path(__file__).resolve().parents[2]
TASK = PACK_PATH / "tasks/grounded-happy-path-v1.json"


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    for path in ("tasks", "evals/smoke", "evals/golden", "fixtures", "licenses"):
        shutil.copytree(ROOT / path, tmp_path / path)
    return tmp_path


def rewrite(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_pack_inventory_and_schema() -> None:
    pack = load_task_pack(ROOT)
    assert len(pack.tasks) == len(pack.cases) == 6
    assert {t.scenario_class for t in pack.tasks} == set(SCENARIOS)
    assert {(t.task_id, t.task_version, t.scenario_class) for t in pack.tasks} == {
        (task_id, VERSION, scenario) for task_id, scenario in TASK_CHOICES
    }
    assert all(case.case_version == VERSION for case in pack.cases)
    schema = json.loads((ROOT / PACK_PATH / "schema/task.schema.json").read_text())
    assert set(schema["properties"]) == set(schema["required"]) == TASK_FIELDS
    assert schema["additionalProperties"] is False
    for task in pack.tasks:
        assert task.substantive_review.status == "DRAFT"
        assert task.substantive_review.reviewer_id is None
        assert task.substantive_review.reviewed_at is None
        assert not task.prospect_demo_eligible


def update_task_identity(
    entry: dict[str, Any],
    task: dict[str, Any],
    case: dict[str, Any],
    task_id: str,
    version: str,
) -> None:
    """Keep ordinary task/manifest/golden cross-references consistent."""
    entry.update(id=task_id, version=version)
    task.update(task_id=task_id, task_version=version)
    task["configuration_options"].update(
        domain_task_id=task_id, domain_task_version=version
    )
    case.update(
        case_id=f"golden.{task_id}",
        domain_task_id=task_id,
        domain_task_version=version,
    )
    case["expected_configuration_options"].update(
        domain_task_id=task_id, domain_task_version=version
    )


@pytest.mark.parametrize(
    "mutation", ["extra", "renamed", "version", "scenario-mismatch"]
)
def test_unsupported_task_inventory(repository: Path, mutation: str) -> None:
    manifest_path = repository / PACK_PATH / "manifest.json"
    golden_path = repository / GOLDEN_PATH
    manifest = json.loads(manifest_path.read_text())
    golden = json.loads(golden_path.read_text())
    entry = manifest["tasks"][0]
    task = json.loads((repository / PACK_PATH / entry["path"]).read_text())
    case = next(c for c in golden["cases"] if c["domain_task_id"] == entry["id"])
    task_id, version = entry["id"], entry["version"]
    if mutation == "extra":
        entry, case = deepcopy(entry), deepcopy(case)
        entry["path"] = "tasks/additional-grounded-v1.json"
        manifest["tasks"].append(entry)
        golden["cases"].append(case)
        task_id = "trade-regulatory.additional-grounded"
    elif mutation == "renamed":
        task_id = "trade-regulatory.renamed-grounded"
    elif mutation == "version":
        version = "2.0.0"
    else:
        # Swap supported IDs without changing either task's scenario-specific content.
        other_entry = manifest["tasks"][1]
        other_path = repository / PACK_PATH / other_entry["path"]
        other_task = json.loads(other_path.read_text())
        other_case = next(
            c for c in golden["cases"] if c["domain_task_id"] == other_entry["id"]
        )
        task_id = other_entry["id"]
        update_task_identity(other_entry, other_task, other_case, entry["id"], version)
        rewrite(other_path, other_task)
    update_task_identity(entry, task, case, task_id, version)
    rewrite(repository / PACK_PATH / entry["path"], task)
    rewrite(manifest_path, manifest)
    rewrite(golden_path, golden)
    with pytest.raises(ValueError, match="unsupported v1 task inventory"):
        load_task_pack(repository)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "nested-duplicate",
        "missing",
        "extra",
        "invalid-id",
        "version",
        "enum",
        "status",
        "gate",
        "context",
        "context-version",
        "source",
        "source-version",
        "chunk",
        "ordinal",
        "duplicate-source",
        "rubric",
        "fixture",
        "options",
        "safe-flags",
        "permission",
        "approve",
        "draft-eligible",
        "fake-review",
        "unknown-review",
        "unknown-substantive",
        "null-source",
        "boolean-ordinal",
        "unicode",
        "finite",
        "nonobject",
        "blank",
        "expected-extra",
        "source-extra",
    ],
)
def test_invalid_task_rejected(repository: Path, mutation: str) -> None:
    path = repository / TASK
    raw = json.loads(path.read_text())
    if mutation == "duplicate":
        path.write_text(
            path.read_text().replace(
                '"schema_version": "1"', '"schema_version": "1", "schema_version": "1"'
            )
        )
    elif mutation == "nested-duplicate":
        path.write_text(
            path.read_text().replace('"gate": "PASS"', '"gate": "PASS", "gate": "PASS"')
        )
    else:
        if mutation == "missing":
            del raw["query"]
        elif mutation == "extra":
            raw["execute"] = "anything"
        elif mutation == "invalid-id":
            raw["task_id"] = "../bad"
        elif mutation == "version":
            raw["task_version"] = "latest"
        elif mutation == "enum":
            raw["scenario_class"] = "NEW"
        elif mutation == "status":
            raw["expected"]["criteria"]["authorized-source"] = "SKIP"
        elif mutation == "gate":
            raw["expected"]["gate"] = "ALLOW"
        elif mutation == "context":
            raw["context_ref"]["id"] = "context.missing"
        elif mutation == "context-version":
            raw["context_ref"]["version"] = "2.0.0"
        elif mutation == "source":
            raw["sources"][0]["source_id"] = "unregistered"
        elif mutation == "source-version":
            raw["sources"][0]["source_version"] = "2.0.0"
        elif mutation == "chunk":
            raw["sources"][0]["chunk_id"] = "unregistered"
        elif mutation == "ordinal":
            raw["sources"][0]["ordinal"] = 1
        elif mutation == "duplicate-source":
            raw["sources"].append(raw["sources"][0])
        elif mutation == "rubric":
            raw["automated_control_ref"]["rubric_version"] = "2.0.0"
        elif mutation == "fixture":
            raw["model_fixture_ref"]["id"] = "unregistered"
        elif mutation == "options":
            raw["configuration_options"]["domain_task_id"] = "different"
        elif mutation == "safe-flags":
            raw["expected"]["retrieval_called"] = False
        elif mutation == "permission":
            raw["expected"]["permission_state"] = "BLOCK"
        elif mutation == "approve":
            raw["expected"]["gate"] = "BLOCK"
        elif mutation == "draft-eligible":
            raw["prospect_demo_eligible"] = True
        elif mutation == "fake-review":
            raw["substantive_review"]["reviewer_id"] = "invented"
        elif mutation == "unknown-review":
            raw["substantive_review"]["status"] = "PENDING"
        elif mutation == "unknown-substantive":
            raw["substantive_rubric_ref"]["version"] = "2.0.0"
        elif mutation == "null-source":
            raw["sources"] = None
        elif mutation == "boolean-ordinal":
            raw["sources"][0]["ordinal"] = False
        elif mutation == "unicode":
            raw["task_text"] = "\ud800"
        elif mutation == "finite":
            raw["expected"]["retrieval_called"] = float("nan")
        elif mutation == "nonobject":
            raw = []
        elif mutation == "blank":
            raw["task_text"] = " "
        elif mutation == "expected-extra":
            raw["expected"]["override"] = True
        elif mutation == "source-extra":
            raw["sources"][0]["license_ref"] = "duplicated-truth"
        rewrite(path, raw)
    with pytest.raises((ValueError, TypeError)):
        load_task_pack(repository)


@pytest.mark.parametrize(
    "mutation",
    [
        "small",
        "large",
        "coverage",
        "duplicate",
        "identity",
        "extra-artifact",
        "traversal",
        "symlink",
        "schema",
    ],
)
def test_manifest_invariants(repository: Path, mutation: str, tmp_path: Path) -> None:
    path = repository / PACK_PATH / "manifest.json"
    raw = json.loads(path.read_text())
    if mutation == "small":
        raw["tasks"] = raw["tasks"][:4]
    elif mutation == "large":
        raw["tasks"] *= 2
    elif mutation == "coverage":
        raw["tasks"].pop()
    elif mutation == "duplicate":
        raw["tasks"][1] = raw["tasks"][0]
    elif mutation == "identity":
        raw["tasks"][0]["id"] = "wrong"
    elif mutation == "extra-artifact":
        (repository / PACK_PATH / "extra.json").write_text("{}")
    elif mutation == "traversal":
        raw["tasks"][0]["path"] = "../outside.json"
    elif mutation == "symlink":
        path_to_task = repository / TASK
        external = tmp_path.parent / (tmp_path.name + "-external.json")
        external.write_bytes(path_to_task.read_bytes())
        path_to_task.unlink()
        path_to_task.symlink_to(external)
    else:
        schema = repository / PACK_PATH / "schema/task.schema.json"
        rewrite(schema, {})
    rewrite(path, raw)
    with pytest.raises((OSError, ValueError)):
        load_task_pack(repository)


@pytest.mark.parametrize("manifest", ["corpus", "contexts"])
@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "hash", "license", "version", "payload"]
)
def test_canonical_references(repository: Path, manifest: str, mutation: str) -> None:
    path = repository / "fixtures" / manifest / "manifest.json"
    raw = json.loads(path.read_text())
    entries = raw["records" if manifest == "corpus" else "fixtures"]
    if mutation == "missing":
        entries.pop(0)
    elif mutation == "duplicate":
        entries.append(entries[0])
    elif mutation == "hash":
        entries[0]["content_hash"] = "sha256:" + "0" * 64
    elif mutation == "license":
        entries[0]["license_ref"] = "unregistered"
    elif mutation == "version":
        entries[0]["version"] = "2.0.0"
    else:
        (repository / entries[0]["path"]).write_text("{}")
    rewrite(path, raw)
    with pytest.raises(ValueError):
        load_task_pack(repository)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "missing",
        "orphan",
        "identity",
        "options",
        "gate",
        "extra",
    ],
)
def test_golden_references(repository: Path, mutation: str) -> None:
    path = repository / GOLDEN_PATH
    raw = json.loads(path.read_text())
    case = raw["cases"][0]
    if mutation == "duplicate":
        raw["cases"].append(case)
    elif mutation == "missing":
        raw["cases"].pop()
    elif mutation == "orphan":
        case["domain_task_id"] = "orphan"
    elif mutation == "identity":
        case["domain_task_version"] = "2.0.0"
    elif mutation == "options":
        case["expected_configuration_options"]["scenario_class"] = "different"
    elif mutation == "gate":
        case["expected"]["gate"] = "BLOCK"
    else:
        case["unexpected"] = True
    rewrite(path, raw)
    with pytest.raises(ValueError):
        load_task_pack(repository)


@pytest.mark.parametrize(
    ("version", "error"),
    [
        ("v1", "malformed identity or version"),
        ("2.0.0", "unsupported golden case version"),
    ],
)
def test_invalid_golden_case_version(
    repository: Path, version: str, error: str
) -> None:
    path = repository / GOLDEN_PATH
    raw = json.loads(path.read_text())
    raw["cases"][0]["case_version"] = version
    rewrite(path, raw)
    with pytest.raises(ValueError, match=error):
        load_task_pack(repository)


@pytest.mark.parametrize(
    "mutation",
    [
        "remove",
        "rename",
        "version",
        "kind",
        "evaluator-version",
        "criticality",
        "task",
        "rubric",
    ],
)
def test_p0_controls_cannot_change(repository: Path, mutation: str) -> None:
    path = repository / "evals/smoke/rubric.json"
    raw = json.loads(path.read_text())
    criterion = raw["rubric"]["criteria"][0]
    if mutation == "remove":
        raw["rubric"]["criteria"].pop()
    elif mutation == "rename":
        criterion["criterion_id"] = "renamed"
    elif mutation == "version":
        criterion["criterion_version"] = "2.0.0"
    elif mutation == "kind":
        criterion["evaluator_kind"] = "permission-boundary"
    elif mutation == "evaluator-version":
        criterion["evaluator_version"] = "2.0.0"
    elif mutation == "criticality":
        criterion["criticality"] = "NON_CRITICAL"
    elif mutation == "task":
        raw["task_version"] = "2.0.0"
    else:
        raw["rubric"]["rubric_version"] = "2.0.0"
    rewrite(path, raw)
    with pytest.raises(ValueError):
        load_task_pack(repository)


@pytest.mark.parametrize("flag", ["retrieval_called", "model_called"])
def test_permission_stop_cannot_claim_protected_calls(flag: str) -> None:
    raw = (
        load_task_pack(ROOT)
        .select("trade-regulatory.permission-block")
        .expected.as_dict()
    )
    raw[flag] = True
    with pytest.raises(ValueError):
        parse_expected(raw)


def test_approved_substantive_review_requires_all_evidence(repository: Path) -> None:
    path = repository / TASK
    raw = json.loads(path.read_text())
    raw["substantive_review"]["status"] = "APPROVED"
    raw["prospect_demo_eligible"] = True
    rewrite(path, raw)
    with pytest.raises(ValueError):
        load_task_pack(repository)


def test_canonical_license_registry_reference_is_required() -> None:
    from test_fixture_validation import VALIDATOR, registry

    entries = registry()
    del entries["fixture:synthetic-corpus"]
    with pytest.raises(ValueError, match="unknown license reference"):
        VALIDATOR.validate_corpus(ROOT / "fixtures/corpus/manifest.json", entries)


def test_task_artifacts_have_explicit_synthetic_license_coverage() -> None:
    from test_fixture_validation import registry

    entry = registry()["fixture:trade-regulatory-tasks"]
    paths = {
        str(p.relative_to(ROOT)) for p in (ROOT / PACK_PATH).rglob("*") if p.is_file()
    }
    paths.add(GOLDEN_PATH)
    registered = entry["repository_paths"]
    assert isinstance(registered, list)
    assert paths <= set(registered)
    assert entry["source"] == "Repository-authored fixture"
    assert entry["version_or_commit"] == "1.0.0"
