"""Minimal FastAPI/Jinja placeholder for DSL-105 preview validation."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from privilab.config import Settings, load_settings

TEMPLATE_DIR = Path(__file__).parent / "web" / "templates"
templates = Jinja2Templates(directory=TEMPLATE_DIR)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the placeholder application without product integrations."""
    active_settings = settings or load_settings()
    application = FastAPI(
        title=active_settings.title,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "title": active_settings.title,
                "banner": active_settings.reference_banner,
                "environment": active_settings.environment,
            },
        )

    return application


app = create_app()
