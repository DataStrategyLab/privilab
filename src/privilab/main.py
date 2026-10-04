"""Local FastAPI/Jinja presentation of the trusted fixture run sequence."""

import re
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from privilab.adapters.storage import SQLiteProvenanceStore
from privilab.application import RunId, RunOutcome, RunProvenance, RunStatus
from privilab.application.run_review import (
    ReviewConflict,
    ReviewDecision,
    RunNotFound,
    RunReviewService,
    RunReviewView,
)
from privilab.application.trade_regulatory_tasks import TASK_CHOICES
from privilab.config import Settings, load_settings
from privilab.domain import SyntheticRequestContext
from privilab.web.presentation import (
    CONTEXT_LABELS,
    CRITERION_LABELS,
    REASON_LABELS,
    SCENARIO_COPY,
)
from privilab.web.preview import CONTEXT_CHOICES, QUERY, TASK_TEXT, open_preview_run

TEMPLATE_DIR = Path(__file__).parent / "web" / "templates"
STATIC_DIR = Path(__file__).parent / "web" / "static"
templates = Jinja2Templates(directory=TEMPLATE_DIR)


def _unavailable_response() -> HTMLResponse:
    # This fixed fallback also works if template rendering itself failed.
    return HTMLResponse(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>PriviLAB — preview unavailable</title></head><body><main>"
        "<p><strong>Synthetic/reference demo only</strong></p>"
        "<h1>Preview unavailable</h1>"
        "<p>The current run could not be displayed. Please try again.</p>"
        '<a href="/">Start a new run</a></main></body></html>',
        status_code=500,
    )


def _run_values(outcome: RunOutcome | None, record: RunProvenance) -> dict[str, object]:
    """Select metadata for presentation without calculating progression."""
    configuration = record.configuration
    permission = record.permission
    generated = record.status is RunStatus.GENERATED
    result = outcome.result if generated and outcome else None
    # Disclosure only: do not modify the result evaluated by RunReviewService.
    # A matching pair permits display, never confers citation/grounding approval.
    authorized_pairs = {
        (source_id, chunk.chunk_id)
        for source_id, _version, chunk in record.chunks_in_retrieval_order
    }
    options = dict(configuration.options)
    scenario = options.get("domain_task_id") or options.get("scenario")
    scenario_copy = SCENARIO_COPY.get(scenario or "")
    context_rows = tuple(
        (label, CONTEXT_LABELS.get(value, value) if value else "Not provided", value)
        for label, value in (
            ("Synthetic user", record.context.user_id),
            ("Synthetic role", record.context.role_id),
            ("Synthetic client", record.context.client_id),
            ("Synthetic matter", record.context.matter_id),
            ("Synthetic workflow", record.context.workflow_id),
        )
    )
    return {
        "scenario_label": scenario_copy[0] if scenario_copy else "Recorded scenario",
        "scenario_description": scenario_copy[1] if scenario_copy else None,
        "context_rows": context_rows,
        "source_count": len(record.sources),
        "provider_label": configuration.provider_id,
        "model_label": configuration.model_id,
        "run_status": record.status.value,
        "permission_state": (permission.state.value if permission else None),
        "stop_reason": record.stop_reason.value if record.stop_reason else None,
        "conditions": permission.unresolved_condition_ids if permission else (),
        "failure_stage": record.failure_stage.value if record.failure_stage else None,
        "retrieval_called": record.retrieval_called,
        "model_called": record.model_called,
        "answer": result.answer_text if result else None,
        "citation_rows": tuple(
            (citation.source_id, citation.chunk_id)
            if (citation.source_id, citation.chunk_id) in authorized_pairs
            else None
            for citation in result.citations
        )
        if result
        else (),
        "source_rows": (
            tuple(
                (
                    source_id,
                    version,
                    chunk.chunk_id,
                    chunk.ordinal,
                    chunk.retrieval_position,
                )
                for source_id, version, chunk in record.chunks_in_retrieval_order
            )
            if generated
            else ()
        ),
        "run_detail": (
            ("Run ID", record.run_id.value),
            ("Scenario", scenario),
            ("Terminal status", record.status.value),
            ("Started (UTC)", record.started_at.isoformat()),
            ("Completed (UTC)", record.completed_at.isoformat()),
            ("User", record.context.user_id),
            ("Role", record.context.role_id),
            ("Client", record.context.client_id),
            ("Matter", record.context.matter_id),
            ("Workflow", record.context.workflow_id),
            ("Permission policy", permission.policy_id if permission else None),
            ("Policy version", permission.policy_version if permission else None),
            ("Configuration", configuration.configuration_id),
            ("Configuration version", configuration.configuration_version),
            ("Configuration hash", record.configuration_hash),
            ("Configured provider", configuration.provider_id),
            ("Provider version", configuration.provider_version),
            ("Configured model", configuration.model_id),
            ("Model version", configuration.model_version),
            *(
                (name, value)
                for name, value in configuration.options
                if name
                in {
                    "task_pack_id",
                    "task_pack_version",
                    "domain_task_id",
                    "domain_task_version",
                    "scenario_class",
                }
            ),
        ),
    }


async def _form_choice(request: Request, field: str, choices: set[str]) -> str:
    if request.query_params:
        raise ValueError("unexpected query fields")
    media_type = (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    if media_type != "application/x-www-form-urlencoded":
        raise ValueError("unsupported form encoding")
    body = bytearray()
    async for part in request.stream():
        if len(body) + len(part) > 1024:
            raise ValueError("form is too large")
        body.extend(part)
    payload = body.decode("utf-8", errors="strict")
    if re.search(r"%(?![0-9a-fA-F]{2})", payload):
        raise ValueError("invalid percent encoding")
    fields = parse_qs(
        payload,
        keep_blank_values=True,
        strict_parsing=True,
        encoding="utf-8",
        errors="strict",
        max_num_fields=1,
    )
    if set(fields) != {field} or len(fields[field]) != 1:
        raise ValueError("invalid form fields")
    choice = fields[field][0]
    if choice not in choices:
        raise ValueError("unknown synthetic context")
    return choice


def _web_run_id(value: str) -> RunId:
    parsed = UUID(value)
    if str(parsed) != value or parsed.version != 4:
        raise ValueError("invalid preview run ID")
    return RunId(value)


def _review_values(view: RunReviewView) -> dict[str, object]:
    evaluation = view.evaluation
    review = view.review
    approval_explanation = None
    if ReviewDecision.APPROVE not in view.allowed_decisions:
        if review is not None:
            approval_explanation = "A final decision is already recorded for this run."
        elif view.run.status is not RunStatus.GENERATED:
            approval_explanation = "This run did not produce a draft for human review."
        elif evaluation is None:
            approval_explanation = (
                "Evaluation unavailable or incomplete. This run is not reviewable."
            )
        elif evaluation.gate_status.value == "BLOCK":
            approval_explanation = (
                "The automated critical gate is BLOCK. Approval is unavailable."
            )
        else:
            approval_explanation = "Approval is unavailable for this recorded state."
    return {
        "run_id": view.run.run_id.value,
        "review_state": view.review_state,
        "approval_explanation": approval_explanation,
        "decisions": tuple(
            (decision.value, decision in view.allowed_decisions)
            for decision in ReviewDecision
        ),
        "review_detail": ()
        if review is None
        else (
            ("Decision", review.decision.value),
            ("Local demo reviewer identity", review.reviewer_id),
            ("Reviewed (UTC)", review.reviewed_at.isoformat()),
        ),
        "gate_status": evaluation.gate_status.value if evaluation else None,
        "criteria_summary": tuple(
            (
                CRITERION_LABELS.get(item.criterion_id, item.criterion_id),
                item.criticality.value,
                item.status.value,
                tuple(
                    REASON_LABELS.get(code.value, code.value)
                    for code in item.evidence.reason_codes
                ),
            )
            for item in evaluation.criteria
        )
        if evaluation
        else (),
        "evaluation_detail": ()
        if evaluation is None
        else (
            ("Evaluation record version", evaluation.schema_version),
            ("Evaluated (UTC)", evaluation.evaluated_at.isoformat()),
            ("Task", evaluation.task_id),
            ("Task version", evaluation.task_version),
            ("Rubric", evaluation.rubric_id),
            ("Rubric version", evaluation.rubric_version),
        ),
        "criteria": ()
        if evaluation is None
        else tuple(
            (
                item.criterion_id,
                item.criterion_version,
                item.evaluator_kind.value,
                item.evaluator_version,
                item.criticality.value,
                item.status.value,
                ", ".join(code.value for code in item.evidence.reason_codes),
                item.evidence.source_count,
                item.evidence.citation_count,
            )
            for item in evaluation.criteria
        ),
        "gate_blocks": ()
        if evaluation is None
        else tuple(
            (block.reason_code.value, block.criterion_id, block.criterion_version)
            for block in evaluation.blocks
        ),
        "injection_fixture": any(
            source.source_id == "synthetic-injection-001" for source in view.run.sources
        ),
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the local preview without opening adapters or executing a run."""
    active_settings = settings or load_settings()
    application = FastAPI(
        title=active_settings.title,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def render(
        request: Request,
        *,
        values: dict[str, object] | None = None,
        status_code: int = 200,
        template: str = "index.html",
    ) -> HTMLResponse:
        try:
            return templates.TemplateResponse(
                request=request,
                name=template,
                context={
                    "title": active_settings.title,
                    "banner": active_settings.reference_banner,
                    "environment": active_settings.environment,
                    "choices": tuple(
                        (key, SCENARIO_COPY[key][0])
                        for key in (
                            *(key for key, _label, _context in CONTEXT_CHOICES),
                            *(key for key, _label in TASK_CHOICES),
                        )
                    ),
                    "scenario_guide": tuple(SCENARIO_COPY.values()),
                    "task_text": TASK_TEXT,
                    "query": QUERY,
                    "selected_choice": "standard",
                }
                | (values or {}),
                status_code=status_code,
            )
        except Exception:
            return _unavailable_response()

    def execute(
        request: Request, choice: str, context: SyntheticRequestContext
    ) -> HTMLResponse:
        with open_preview_run(
            active_settings.preview_database,
            context_choice=choice,
            corpus_root=active_settings.preview_corpus_root,
        ) as (service, store):
            outcome, view = RunReviewService(store, store).execute(
                service, context=context, task_text=TASK_TEXT, query=QUERY
            )
            return render(
                request,
                values=_run_values(outcome, view.run)
                | _review_values(view)
                | {"selected_choice": choice},
                status_code=500
                if outcome.status is RunStatus.FAILED or view.evaluation is None
                else 200,
            )

    def execute_domain_task(request: Request, choice: str) -> HTMLResponse:
        # Explicit local task selection is the only preview artifact-loading path.
        # Reuse the configured canonical corpus location; do not discover a checkout.
        from privilab.evals.trade_regulatory import open_task_run

        repository = active_settings.preview_corpus_root.parent.parent
        if active_settings.preview_corpus_root != repository / "fixtures/corpus":
            raise ValueError("DSL-117 requires the canonical local checkout layout")
        with open_task_run(
            repository, choice, database_path=active_settings.preview_database
        ) as (task, service, store):
            outcome, view = RunReviewService(store, store).execute(
                service,
                context=task.context,
                task_text=task.task_text,
                query=task.query,
            )
            return render(
                request,
                values=_run_values(outcome, view.run)
                | _review_values(view)
                | {
                    "selected_choice": choice,
                    "task_text": task.task_text,
                    "query": task.query,
                    "domain_task_note": "Internal fixture; substantive review: "
                    + task.substantive_review.status
                    + ". No prospect-demo release is granted.",
                },
                status_code=500
                if outcome.status is RunStatus.FAILED or view.evaluation is None
                else 200,
            )

    @application.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        try:
            return render(request)
        except Exception:
            return _unavailable_response()

    @application.post("/runs", response_class=HTMLResponse)
    async def submit(request: Request) -> HTMLResponse:
        try:
            try:
                choice = await _form_choice(
                    request,
                    "context_choice",
                    {key for key, _, _ in CONTEXT_CHOICES}
                    | {key for key, _ in TASK_CHOICES},
                )
            except ValueError:
                return render(
                    request,
                    values={
                        "form_error": (
                            "Select a listed synthetic context and submit again."
                        )
                    },
                    status_code=400,
                )
            if choice in {key for key, _ in TASK_CHOICES}:
                return await run_in_threadpool(execute_domain_task, request, choice)
            context = next(
                value for key, _label, value in CONTEXT_CHOICES if key == choice
            )
            return await run_in_threadpool(execute, request, choice, context)
        except Exception:
            return _unavailable_response()

    @application.get("/runs", response_class=HTMLResponse)
    def history(request: Request) -> HTMLResponse:
        try:
            if request.query_params:
                return render(
                    request,
                    values={"form_error": "History takes no query fields."},
                    status_code=400,
                )
            rows: tuple[tuple[object, ...], ...] = ()
            if active_settings.preview_database.exists():
                with closing(
                    SQLiteProvenanceStore(active_settings.preview_database)
                ) as store:
                    views = RunReviewService(store, store).recent()
                    rows = tuple(
                        (
                            view.run.run_id.value,
                            view.run.completed_at.isoformat(),
                            view.run.status.value,
                            view.run.permission.state.value
                            if view.run.permission
                            else "Unavailable",
                            view.evaluation.gate_status.value
                            if view.evaluation
                            else "Unavailable",
                            view.review_state,
                        )
                        for view in views
                    )
            return render(
                request, template="history.html", values={"history_rows": rows}
            )
        except Exception:
            return _unavailable_response()

    @application.get("/runs/{run_id}", response_class=HTMLResponse)
    def detail(request: Request, run_id: str) -> HTMLResponse:
        try:
            try:
                identity = _web_run_id(run_id)
            except ValueError:
                return render(
                    request,
                    values={"form_error": "Invalid run identifier."},
                    status_code=400,
                )
            if not active_settings.preview_database.exists():
                raise RunNotFound
            with closing(
                SQLiteProvenanceStore(active_settings.preview_database)
            ) as store:
                view = RunReviewService(store, store).get(identity)
            return render(
                request,
                values=_run_values(None, view.run)
                | _review_values(view)
                | {"reopened": True},
            )
        except RunNotFound:
            return render(
                request, values={"form_error": "Run not found."}, status_code=404
            )
        except Exception:
            return _unavailable_response()

    def record_decision(run_id: RunId, decision: ReviewDecision) -> None:
        if not active_settings.preview_database.exists():
            raise RunNotFound
        with closing(SQLiteProvenanceStore(active_settings.preview_database)) as store:
            RunReviewService(store, store).decide(run_id, decision)

    @application.post("/runs/{run_id}/review", response_class=HTMLResponse)
    async def review(request: Request, run_id: str) -> Response:
        try:
            try:
                identity = _web_run_id(run_id)
                decision = ReviewDecision(
                    await _form_choice(
                        request, "decision", {item.value for item in ReviewDecision}
                    )
                )
            except ValueError:
                return render(
                    request,
                    values={"form_error": "Invalid review request."},
                    status_code=400,
                )
            await run_in_threadpool(record_decision, identity, decision)
            return RedirectResponse(url=f"/runs/{identity.value}", status_code=303)
        except RunNotFound:
            return render(
                request, values={"form_error": "Run not found."}, status_code=404
            )
        except ReviewConflict:
            return render(
                request,
                values={
                    "form_error": "Human decision is unavailable or already recorded."
                },
                status_code=409,
            )
        except Exception:
            return _unavailable_response()

    return application


app = create_app()
