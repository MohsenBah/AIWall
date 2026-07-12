# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
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
DEFAULT_SUMMARY_WINDOW_HOURS = 24


def build_templates() -> Jinja2Templates:
    return Jinja2Templates(directory=str(TEMPLATES_DIR))


def create_web_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    def _load_events(
        audit_writer,
        *,
        decision: str | None,
        provider: str | None,
    ):
        normalized_decision = decision or None
        normalized_provider = provider or None
        events = audit_writer.list_recent(
            limit=DEFAULT_EVENT_LIMIT,
            decision=normalized_decision,
            provider=normalized_provider,
        )
        providers = audit_writer.list_providers()
        return events, providers, normalized_decision, normalized_provider

    @router.get("/", response_class=HTMLResponse)
    async def dashboard(
        request: Request,
        decision: str | None = None,
        provider: str | None = None,
    ) -> HTMLResponse:
        audit_writer = request.app.state.audit_writer
        events, providers, selected_decision, selected_provider = _load_events(
            audit_writer,
            decision=decision,
            provider=provider,
        )
        summary = audit_writer.summary(window_hours=DEFAULT_SUMMARY_WINDOW_HOURS)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "events": events,
                "event_limit": DEFAULT_EVENT_LIMIT,
                "summary": summary,
                "providers": providers,
                "selected_decision": selected_decision,
                "selected_provider": selected_provider,
            },
        )

    @router.get("/partials/events", response_class=HTMLResponse)
    async def events_partial(
        request: Request,
        decision: str | None = None,
        provider: str | None = None,
    ) -> HTMLResponse:
        audit_writer = request.app.state.audit_writer
        events, providers, selected_decision, selected_provider = _load_events(
            audit_writer,
            decision=decision,
            provider=provider,
        )
        return templates.TemplateResponse(
            request,
            "partials/events_table.html",
            {
                "events": events,
                "providers": providers,
                "selected_decision": selected_decision,
                "selected_provider": selected_provider,
            },
        )

    return router


def register_web(app: FastAPI) -> None:
    """Mount the dashboard. Requires Jinja2; callers should guard the import."""
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(create_web_router(build_templates()))
