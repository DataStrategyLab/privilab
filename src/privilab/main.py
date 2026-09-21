"""Local FastAPI/Jinja presentation of the trusted fixture run sequence."""

import re
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from privilab.application import RunOutcome, RunProvenance, RunStatus
from privilab.config import Settings, load_settings
from privilab.domain import SyntheticRequestContext
from privilab.web.preview import CONTEXT_CHOICES, QUERY, TASK_TEXT, open_preview_run

TEMPLATE_DIR = Path(__file__).parent / "web" / "templates"
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
        '<a href="/">Return to the new-run form</a></main></body></html>',
        status_code=500,
    )


def _run_values(outcome: RunOutcome, record: RunProvenance) -> dict[str, object]:
    """Select metadata for presentation without calculating progression."""
    configuration = record.configuration
    permission = record.permission
    generated = outcome.status is RunStatus.GENERATED
    return {
        "run_status": outcome.status.value,
        "permission_state": (
            outcome.permission_result.state.value if outcome.permission_result else None
        ),
        "stop_reason": record.stop_reason.value if record.stop_reason else None,
        "conditions": permission.unresolved_condition_ids if permission else (),
        "failure_stage": outcome.failure_stage.value if outcome.failure_stage else None,
        "retrieval_called": record.retrieval_called,
        "model_called": record.model_called,
        "answer": outcome.result.answer_text if generated and outcome.result else None,
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
        ),
    }


async def _context_choice(request: Request) -> str:
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
    if set(fields) != {"context_choice"} or len(fields["context_choice"]) != 1:
        raise ValueError("invalid form fields")
    choice = fields["context_choice"][0]
    if choice not in {key for key, _label, _context in CONTEXT_CHOICES}:
        raise ValueError("unknown synthetic context")
    return choice


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the local preview without opening adapters or executing a run."""
    active_settings = settings or load_settings()
    application = FastAPI(
        title=active_settings.title,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def render(
        request: Request,
        *,
        values: dict[str, object] | None = None,
        status_code: int = 200,
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "title": active_settings.title,
                "banner": active_settings.reference_banner,
                "environment": active_settings.environment,
                "choices": tuple((key, label) for key, label, _ in CONTEXT_CHOICES),
                "task_text": TASK_TEXT,
                "query": QUERY,
                "selected_choice": "standard",
            }
            | (values or {}),
            status_code=status_code,
        )

    def execute(
        request: Request, choice: str, context: SyntheticRequestContext
    ) -> HTMLResponse:
        with open_preview_run() as (service, store):
            outcome = service.run(context=context, task_text=TASK_TEXT, query=QUERY)
            record = store.get(outcome.run_id)
            if record is None:
                return _unavailable_response()
            return render(
                request,
                values=_run_values(outcome, record) | {"selected_choice": choice},
                status_code=500 if outcome.status is RunStatus.FAILED else 200,
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
                choice = await _context_choice(request)
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
            context = next(
                value for key, _label, value in CONTEXT_CHOICES if key == choice
            )
            return await run_in_threadpool(execute, request, choice, context)
        except Exception:
            return _unavailable_response()

    return application


app = create_app()
