"""Explicit, dependency-minimal loading of the bounded DSL-117 task pack.

Importing this module performs no I/O. Expectations never grant runtime authority.
Canonical license registry validation belongs to scripts/validate_fixtures.py.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from privilab.adapters.models.governed_fixture import load_governed_fixture
from privilab.domain import SyntheticRequestContext
from privilab.evals.contracts import (
    CriterionCriticality,
    TaskDefinition,
    p0_task_definition,
    validate_p0_task,
)

PACK_PATH = Path("tasks/trade_regulatory/research_v1")
GOLDEN_PATH = "evals/golden/trade_regulatory_v1/cases.json"
PACK_ID = "trade-regulatory-research"
VERSION = "1.0.0"
SCENARIOS = (
    "GROUNDED_HAPPY_PATH",
    "INSUFFICIENT_SOURCE",
    "PERMISSION_BLOCK",
    "CRITICAL_EVAL_FAILURE",
    "CITATION_GROUNDING_CHALLENGE",
    "MALICIOUS_SOURCE_INJECTION",
)
TASK_CHOICES = tuple(
    ("trade-regulatory." + value.lower().replace("_", "-"), value)
    for value in SCENARIOS
)
CRITERIA = (
    "authorized-source",
    "citation-resolution",
    "permission-boundary",
    "provenance-completeness",
)
CONTROL_REF = {
    "task_id": "p0-source-grounded-output",
    "task_version": VERSION,
    "rubric_id": "p0-deterministic-critical-gate",
    "rubric_version": VERSION,
}
RUBRIC_ID = "trade-regulatory-substantive-review"
DOMAIN_CRITERIA = (
    "proposition-support",
    "scope-discipline",
    "uncertainty-handling",
    "draft-clarity",
)
SOURCE_IDENTITIES = {
    "corpus.synthetic-trade-notice.001": (
        "synthetic-trade-notice-001",
        "synthetic-trade-notice-chunk-001",
    ),
    "corpus.synthetic-injection.001": (
        "synthetic-injection-001",
        "synthetic-injection-chunk-001",
    ),
}
FIXTURE_SUFFIXES = {
    "GROUNDED_HAPPY_PATH": "grounded",
    "INSUFFICIENT_SOURCE": "insufficient-source",
    "PERMISSION_BLOCK": "grounded",
    "CRITICAL_EVAL_FAILURE": "missing-citation",
    "CITATION_GROUNDING_CHALLENGE": "missing-chunk",
    "MALICIOUS_SOURCE_INJECTION": "grounded",
}
TASK_FIELDS = {
    "schema_version",
    "task_id",
    "task_version",
    "scenario_class",
    "title",
    "task_text",
    "query",
    "context_ref",
    "sources",
    "model_fixture_ref",
    "automated_control_ref",
    "expected",
    "expected_output_behavior",
    "safe_failure",
    "configuration_options",
    "substantive_rubric_ref",
    "substantive_review",
    "prospect_demo_eligible",
}
_ID = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*\Z")
_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError("non-finite JSON value")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_pairs,
        parse_constant=_invalid_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("JSON document must be an object")
    return value


def _object(value: Any, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("fields do not match the task-pack contract")
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError("expected non-empty trimmed text")
    if "\x00" in value:
        raise ValueError("text contains NUL")
    value.encode("utf-8")
    return value


def _identity(value: Any, *, version: bool = False) -> str:
    result = _text(value)
    if not (_VERSION if version else _ID).fullmatch(result):
        raise ValueError("malformed identity or version")
    return result


def _ref(value: Any) -> tuple[str, str]:
    raw = _object(value, {"id", "version"})
    return _identity(raw["id"]), _identity(raw["version"], version=True)


def _list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("expected array")
    return value


def _boolean(value: Any) -> bool:
    if type(value) is not bool:
        raise ValueError("expected boolean")
    return value


def inside(root: Path, relative: Any) -> Path:
    name = _text(relative)
    parts = PurePosixPath(name)
    if parts.is_absolute() or ".." in parts.parts or "\\" in name:
        raise ValueError("invalid artifact path")
    result = (root / name).resolve(strict=True)
    result.relative_to(root.resolve(strict=True))
    if not result.is_file():
        raise ValueError("artifact must be a file")
    return result


@dataclass(frozen=True, slots=True)
class Expected:
    permission_state: str
    run_status: str
    retrieval_called: bool
    model_called: bool
    criteria: tuple[tuple[str, str], ...]
    gate: str
    review_state: str
    allowed_decisions: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "permission_state": self.permission_state,
            "run_status": self.run_status,
            "retrieval_called": self.retrieval_called,
            "model_called": self.model_called,
            "criteria": dict(self.criteria),
            "gate": self.gate,
            "review_state": self.review_state,
            "allowed_decisions": list(self.allowed_decisions),
        }


def parse_expected(value: Any) -> Expected:
    raw = _object(value, set(Expected.__dataclass_fields__))
    criteria = _object(raw["criteria"], set(CRITERIA))
    if any(
        not isinstance(v, str) or v not in {"PASS", "FAIL", "ERROR", "UNKNOWN"}
        for v in criteria.values()
    ):
        raise ValueError("invalid automated criterion status")
    for name, allowed in (
        ("permission_state", {"ALLOW", "CONDITIONAL", "BLOCK", "UNKNOWN"}),
        ("run_status", {"GENERATED", "PERMISSION_STOPPED", "FAILED"}),
        ("gate", {"PASS", "BLOCK"}),
        ("review_state", {"PENDING", "NOT REVIEWABLE"}),
    ):
        if not isinstance(raw[name], str) or raw[name] not in allowed:
            raise ValueError("invalid expectation enum")
    retrieval = _boolean(raw["retrieval_called"])
    model = _boolean(raw["model_called"])
    generated = raw["run_status"] == "GENERATED"
    if generated and (raw["permission_state"] != "ALLOW" or not retrieval or not model):
        raise ValueError("generated expectation contradicts progression")
    if raw["run_status"] == "PERMISSION_STOPPED" and (
        raw["permission_state"] == "ALLOW" or retrieval or model
    ):
        raise ValueError("permission-stopped expectation contradicts progression")
    if model and not retrieval:
        raise ValueError("model requires retrieval")
    gate = (
        "PASS" if generated and all(v == "PASS" for v in criteria.values()) else "BLOCK"
    )
    decisions = [] if not generated else ["REJECT", "REQUEST_REVISION"]
    if gate == "PASS":
        decisions.insert(0, "APPROVE")
    if (
        raw["gate"] != gate
        or raw["allowed_decisions"] != decisions
        or raw["review_state"] != ("PENDING" if generated else "NOT REVIEWABLE")
    ):
        raise ValueError("gate/review expectations contradict governed eligibility")
    return Expected(
        raw["permission_state"],
        raw["run_status"],
        retrieval,
        model,
        tuple(sorted(criteria.items())),
        gate,
        raw["review_state"],
        tuple(decisions),
    )


@dataclass(frozen=True, slots=True)
class SourceReference:
    corpus_id: str
    corpus_version: str
    source_id: str
    source_version: str
    chunk_id: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class SubstantiveReview:
    status: str
    reviewer_id: str | None
    reviewed_at: str | None
    criterion_results: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class DomainTask:
    task_id: str
    task_version: str
    scenario_class: str
    title: str
    task_text: str
    query: str
    context_ref: tuple[str, str]
    context: SyntheticRequestContext
    sources: tuple[SourceReference, ...]
    model_fixture_ref: tuple[str, str]
    expected: Expected
    expected_output_behavior: str
    safe_failure: str
    configuration_options: tuple[tuple[str, str], ...]
    substantive_review: SubstantiveReview
    prospect_demo_eligible: bool


@dataclass(frozen=True, slots=True)
class GoldenCase:
    case_id: str
    case_version: str
    domain_task_id: str
    domain_task_version: str
    expected: Expected
    expected_configuration_options: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class TaskPack:
    tasks: tuple[DomainTask, ...]
    cases: tuple[GoldenCase, ...]

    def select(self, task_id: str, version: str = VERSION) -> DomainTask:
        matches = [
            t for t in self.tasks if (t.task_id, t.task_version) == (task_id, version)
        ]
        if len(matches) != 1:
            raise ValueError("task reference must resolve exactly once")
        return matches[0]


def identity_options(
    task_id: str, version: str, scenario: str
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            {
                "task_pack_id": PACK_ID,
                "task_pack_version": VERSION,
                "domain_task_id": task_id,
                "domain_task_version": version,
                "scenario_class": scenario,
            }.items()
        )
    )


def _record(
    root: Path,
    manifest_name: str,
    identity: tuple[str, str],
    license_ref: str,
    *,
    corpus: bool = False,
) -> tuple[dict[str, Any], Path]:
    manifest_path = inside(root, manifest_name)
    key = "records" if corpus else "fixtures"
    manifest = _object(read_json(manifest_path), {"schema_version", key})
    if manifest["schema_version"] != "1":
        raise ValueError("unsupported canonical manifest version")
    entries = _list(manifest[key])
    seen: set[str] = set()
    selected: tuple[dict[str, Any], Path] | None = None
    fields = {"id", "version", "path", "content_hash", "synthetic", "license_ref"}
    if corpus:
        fields |= {"origin", "permitted_use_basis"}
    for entry in entries:
        raw = _object(entry, fields)
        ref = _identity(raw["id"]), _identity(raw["version"], version=True)
        if ref[0] in seen:
            raise ValueError("duplicate canonical identity")
        seen.add(ref[0])
        path = inside(root, raw["path"])
        path.relative_to(manifest_path.parent)
        if raw["synthetic"] is not True or raw["license_ref"] != license_ref:
            raise ValueError("unregistered synthetic source/license")
        if (
            raw["content_hash"]
            != "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        ):
            raise ValueError("canonical content hash mismatch")
        if corpus:
            _text(raw["origin"])
            _text(raw["permitted_use_basis"])
        if ref == identity:
            selected = raw, path
    if selected is None:
        raise ValueError("canonical reference must resolve exactly once")
    return selected


def source_document(root: Path, ref: SourceReference) -> dict[str, Any]:
    _, path = _record(
        root,
        "fixtures/corpus/manifest.json",
        (ref.corpus_id, ref.corpus_version),
        "fixture:synthetic-corpus",
        corpus=True,
    )
    raw = _object(read_json(path), {"document_id", "title", "text", "synthetic"})
    if (
        raw["synthetic"] is not True
        or raw["document_id"] != ref.source_id
        or ref.source_version != ref.corpus_version
    ):
        raise ValueError("runtime source does not match canonical corpus")
    for name in ("document_id", "title", "text"):
        _text(raw[name])
    return raw


def _review(raw_value: Any, eligible: bool) -> SubstantiveReview:
    raw = _object(raw_value, set(SubstantiveReview.__dataclass_fields__))
    if raw["status"] not in ("DRAFT", "APPROVED", "REJECTED"):
        raise ValueError("invalid substantive review status")
    results = raw["criterion_results"]
    if raw["status"] == "DRAFT":
        if (
            raw["reviewer_id"] is not None
            or raw["reviewed_at"] is not None
            or results != {}
            or eligible
        ):
            raise ValueError("draft cannot claim substantive approval")
    else:
        _text(raw["reviewer_id"])
        stamp = datetime.fromisoformat(_text(raw["reviewed_at"]))
        if stamp.utcoffset() is None:
            raise ValueError("review timestamp must include timezone")
        results = _object(results, set(DOMAIN_CRITERIA))
        if any(v not in ("PASS", "FAIL", "UNKNOWN") for v in results.values()):
            raise ValueError("invalid substantive criterion result")
        if raw["status"] == "APPROVED" and any(v != "PASS" for v in results.values()):
            raise ValueError("release-critical substantive criteria must pass")
        if eligible and raw["status"] != "APPROVED":
            raise ValueError("prospect eligibility requires substantive approval")
    return SubstantiveReview(
        raw["status"],
        raw["reviewer_id"],
        raw["reviewed_at"],
        tuple(sorted(results.items())),
    )


def _task(root: Path, path: Path) -> DomainTask:
    raw = _object(read_json(path), TASK_FIELDS)
    identity = _identity(raw["task_id"]), _identity(raw["task_version"], version=True)
    scenario = _text(raw["scenario_class"])
    if raw["schema_version"] != "1" or scenario not in SCENARIOS:
        raise ValueError("unsupported task schema/scenario")
    if raw["automated_control_ref"] != CONTROL_REF:
        raise ValueError("task must reference the fixed P0 controls")
    if _ref(raw["substantive_rubric_ref"]) != (RUBRIC_ID, VERSION):
        raise ValueError("unregistered substantive rubric")
    context_ref = _ref(raw["context_ref"])
    context_id = (
        "context.synthetic-blocked.001"
        if scenario == "PERMISSION_BLOCK"
        else "context.synthetic-request.001"
    )
    if context_ref != (context_id, VERSION):
        raise ValueError("context reference does not match scenario")
    _, context_path = _record(
        root,
        "fixtures/contexts/manifest.json",
        context_ref,
        "fixture:synthetic-contexts",
    )
    context = SyntheticRequestContext.from_json(
        context_path.read_text(encoding="utf-8")
    )
    sources: list[SourceReference] = []
    for value in _list(raw["sources"]):
        item = _object(value, set(SourceReference.__dataclass_fields__))
        for name in set(item) - {"ordinal"}:
            _identity(item[name], version=name.endswith("version"))
        if type(item["ordinal"]) is not int or item["ordinal"] != 0:
            raise ValueError("DSL-117 uses one whole-document chunk at ordinal zero")
        ref = SourceReference(**item)
        if SOURCE_IDENTITIES.get(ref.corpus_id) != (ref.source_id, ref.chunk_id):
            raise ValueError("unregistered source/chunk identity")
        if ref.corpus_version != VERSION:
            raise ValueError("unsupported corpus version")
        source_document(root, ref)
        sources.append(ref)
    expected_ids = {"corpus.synthetic-trade-notice.001"}
    if scenario == "MALICIOUS_SOURCE_INJECTION":
        expected_ids.add("corpus.synthetic-injection.001")
    if {s.corpus_id for s in sources} != expected_ids or len(sources) != len(
        expected_ids
    ):
        raise ValueError("scenario source references are missing or duplicated")
    fixture_ref = _ref(raw["model_fixture_ref"])
    if fixture_ref != (
        "model-output.trade-regulatory-" + FIXTURE_SUFFIXES[scenario] + ".001",
        VERSION,
    ):
        raise ValueError("unregistered scenario fixture")
    binding = load_governed_fixture(fixture_ref[0])
    if binding.model_version != fixture_ref[1]:
        raise ValueError("governed fixture version mismatch")
    options = identity_options(*identity, scenario)
    if raw["configuration_options"] != dict(options):
        raise ValueError("configuration identity does not match task")
    eligible = _boolean(raw["prospect_demo_eligible"])
    return DomainTask(
        *identity,
        scenario,
        _text(raw["title"]),
        _text(raw["task_text"]),
        _text(raw["query"]),
        context_ref,
        context,
        tuple(sources),
        fixture_ref,
        parse_expected(raw["expected"]),
        _text(raw["expected_output_behavior"]),
        _text(raw["safe_failure"]),
        options,
        _review(raw["substantive_review"], eligible),
        eligible,
    )


def _controls(root: Path) -> None:
    task = p0_task_definition()
    actual = dict(
        task_id=task.task_id,
        task_version=task.task_version,
        rubric_id=task.rubric.rubric_id,
        rubric_version=task.rubric.rubric_version,
    )
    if actual != CONTROL_REF or len(task.rubric.criteria) != 4:
        raise ValueError("governed P0 identity changed")
    if {c.criterion_id for c in task.rubric.criteria} != set(CRITERIA) or any(
        c.criterion_version != VERSION
        or c.evaluator_version != VERSION
        or c.evaluator_kind.value != c.criterion_id
        or c.criticality is not CriterionCriticality.CRITICAL
        for c in task.rubric.criteria
    ):
        raise ValueError("governed P0 criterion definition changed")
    smoke = TaskDefinition.from_json(
        inside(root, "evals/smoke/rubric.json").read_text()
    )
    validate_p0_task(smoke)
    if smoke != task:
        raise ValueError("automated rubric must match exactly")


def load_task_pack(repository_root: Path) -> TaskPack:
    """Load only on explicit golden/local-preview use, never at package startup."""
    if not repository_root.is_absolute():
        raise ValueError("task repository root must be explicit and absolute")
    root = repository_root.resolve(strict=True)
    pack_root = (root / PACK_PATH).resolve(strict=True)
    pack_root.relative_to(root)
    manifest_path = inside(pack_root, "manifest.json")
    manifest = _object(
        read_json(manifest_path),
        {
            "schema_version",
            "task_pack_id",
            "task_pack_version",
            "tasks",
            "schema",
            "substantive_rubric",
            "documentation",
            "golden_cases",
        },
    )
    if (
        manifest["schema_version"],
        manifest["task_pack_id"],
        manifest["task_pack_version"],
    ) != ("1", PACK_ID, VERSION):
        raise ValueError("unsupported task pack identity")
    if (
        manifest["schema"],
        manifest["substantive_rubric"],
        manifest["documentation"],
        manifest["golden_cases"],
    ) != (
        "schema/task.schema.json",
        "rubrics/substantive-review-v1.json",
        ["README.md"],
        GOLDEN_PATH,
    ):
        raise ValueError("unsupported task pack inventory")
    artifacts = {manifest_path}
    for name in [
        manifest["schema"],
        manifest["substantive_rubric"],
        *manifest["documentation"],
    ]:
        artifacts.add(inside(pack_root, name))
    schema = read_json(inside(pack_root, manifest["schema"]))
    if (
        set(schema.get("properties", {})) != TASK_FIELDS
        or set(schema.get("required", [])) != TASK_FIELDS
        or schema.get("additionalProperties") is not False
    ):
        raise ValueError("documented schema does not match executable outer fields")
    rubric = _object(
        read_json(inside(pack_root, manifest["substantive_rubric"])),
        {"schema_version", "rubric_id", "rubric_version", "criteria"},
    )
    if (rubric["schema_version"], rubric["rubric_id"], rubric["rubric_version"]) != (
        "1",
        RUBRIC_ID,
        VERSION,
    ):
        raise ValueError("unsupported substantive rubric")
    criterion_ids: list[str] = []
    for value in _list(rubric["criteria"]):
        criterion = _object(
            value,
            {"criterion_id", "criterion_version", "release_critical", "description"},
        )
        criterion_ids.append(_identity(criterion["criterion_id"]))
        if (
            criterion["criterion_version"] != VERSION
            or criterion["release_critical"] is not True
        ):
            raise ValueError(
                "substantive review must preserve release-critical criteria"
            )
        _text(criterion["description"])
    if len(criterion_ids) != 4 or set(criterion_ids) != set(DOMAIN_CRITERIA):
        raise ValueError("invalid substantive rubric criteria")
    _controls(root)
    entries = _list(manifest["tasks"])
    if not 5 <= len(entries) <= 10:
        raise ValueError("task count must be between 5 and 10")
    tasks: list[DomainTask] = []
    for value in entries:
        entry = _object(value, {"id", "version", "path"})
        path = inside(pack_root, entry["path"])
        path.relative_to((pack_root / "tasks").resolve())
        if path in artifacts:
            raise ValueError("duplicate task artifact")
        artifacts.add(path)
        task = _task(root, path)
        if (task.task_id, task.task_version) != _ref(
            {"id": entry["id"], "version": entry["version"]}
        ):
            raise ValueError("task manifest identity mismatch")
        tasks.append(task)
    if len({t.task_id for t in tasks}) != len(tasks):
        raise ValueError("duplicate task ID")
    if {t.scenario_class for t in tasks} != set(SCENARIOS):
        raise ValueError("all six scenarios are required")
    inventory = {
        p.absolute() for p in pack_root.rglob("*") if p.is_file() or p.is_symlink()
    }
    if inventory != artifacts:
        raise ValueError("unregistered task pack artifact")
    golden_path = inside(root, GOLDEN_PATH)
    if {
        p.absolute()
        for p in golden_path.parent.rglob("*")
        if p.is_file() or p.is_symlink()
    } != {golden_path}:
        raise ValueError("unregistered golden artifact")
    golden = _object(read_json(golden_path), {"schema_version", "synthetic", "cases"})
    if golden["schema_version"] != "1" or golden["synthetic"] is not True:
        raise ValueError("unsupported golden schema")
    cases: list[GoldenCase] = []
    selection = TaskPack(tuple(tasks), ())
    for value in _list(golden["cases"]):
        case = _object(value, set(GoldenCase.__dataclass_fields__))
        task = selection.select(
            _identity(case["domain_task_id"]),
            _identity(case["domain_task_version"], version=True),
        )
        expected = parse_expected(case["expected"])
        if expected != task.expected or case["expected_configuration_options"] != dict(
            task.configuration_options
        ):
            raise ValueError("golden expectations must match the referenced task")
        cases.append(
            GoldenCase(
                _identity(case["case_id"]),
                _identity(case["case_version"], version=True),
                task.task_id,
                task.task_version,
                expected,
                task.configuration_options,
            )
        )
    if len({c.case_id for c in cases}) != len(cases):
        raise ValueError("duplicate golden case ID")
    if {(c.domain_task_id, c.domain_task_version) for c in cases} != {
        (t.task_id, t.task_version) for t in tasks
    }:
        raise ValueError("golden cases must cover every domain task")
    return TaskPack(tuple(tasks), tuple(cases))
