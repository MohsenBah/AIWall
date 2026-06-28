"""Web control panel routes (server-rendered, no frontend build step)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

DEFAULT_EVENT_LIMIT = 50


def build_templates() -> Jinja2Templates:
    return Jinja2Templates(directory=str(TEMPLATES_DIR))


def create_web_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        audit_writer = request.app.state.audit_writer
        events = audit_writer.list_recent(limit=DEFAULT_EVENT_LIMIT)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {"events": events, "event_limit": DEFAULT_EVENT_LIMIT},
        )

    return router


def register_web(app: FastAPI) -> None:
    """Mount the dashboard. Requires Jinja2; callers should guard the import."""
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(create_web_router(build_templates()))
