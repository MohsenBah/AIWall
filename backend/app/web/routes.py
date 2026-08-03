# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Web control panel routes (server-rendered, no frontend build step)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.policies.overrides import set_policy_enabled
from app.reports.weekly import build_weekly_report, render_markdown
from app.web.privacy import event_detail_context

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

DEFAULT_EVENT_LIMIT = 50
DEFAULT_SUMMARY_WINDOW_HOURS = 24
DEFAULT_TREND_BUCKET_HOURS = 1


def build_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    def bar_height(value: float, maximum: float, *, min_px: int = 2, max_px: int = 120) -> int:
        if maximum <= 0 or value <= 0:
            return min_px if value > 0 else 0
        ratio = min(float(value) / float(maximum), 1.0)
        return max(min_px, int(round(ratio * max_px)))

    templates.env.globals["bar_height"] = bar_height
    return templates


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
        trends = audit_writer.usage_timeseries(
            window_hours=DEFAULT_SUMMARY_WINDOW_HOURS,
            bucket_hours=DEFAULT_TREND_BUCKET_HOURS,
        )
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "events": events,
                "event_limit": DEFAULT_EVENT_LIMIT,
                "summary": summary,
                "trends": trends,
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

    @router.get("/partials/events/{event_id}/detail", response_class=HTMLResponse)
    async def event_detail_partial(request: Request, event_id: int) -> HTMLResponse:
        audit_writer = request.app.state.audit_writer
        event = audit_writer.get_by_id(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        return templates.TemplateResponse(
            request,
            "partials/event_detail.html",
            event_detail_context(event),
        )

    def _load_blocked(request: Request, profile: str | None):
        audit_writer = request.app.state.audit_writer
        profile_store = getattr(request.app.state, "profile_store", None)
        profiles = profile_store.list() if profile_store is not None else []
        profile_names = {str(p.id): p.name for p in profiles}
        selected_profile = profile if profile in profile_names else None
        events = audit_writer.list_recent(
            limit=DEFAULT_EVENT_LIMIT,
            decision="block",
            user_id=selected_profile,
        )
        return {
            "events": events,
            "event_limit": DEFAULT_EVENT_LIMIT,
            "profiles": profiles,
            "profile_names": profile_names,
            "selected_profile": selected_profile,
        }

    @router.get("/blocked", response_class=HTMLResponse)
    async def blocked_review(request: Request, profile: str | None = None) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "blocked.html",
            _load_blocked(request, profile),
        )

    @router.get("/partials/blocked", response_class=HTMLResponse)
    async def blocked_partial(request: Request, profile: str | None = None) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "partials/blocked_table.html",
            _load_blocked(request, profile),
        )

    @router.get("/reports/weekly")
    async def weekly_report(
        request: Request,
        format: str | None = None,
    ) -> Response:
        profile_store = getattr(request.app.state, "profile_store", None)
        if profile_store is None:
            raise HTTPException(status_code=503, detail="Profile store unavailable")
        report = build_weekly_report(request.app.state.audit_writer, profile_store)
        fmt = (format or "").lower()
        if fmt in {"md", "markdown", "text"}:
            return PlainTextResponse(
                render_markdown(report),
                media_type="text/markdown; charset=utf-8",
            )
        return templates.TemplateResponse(
            request,
            "reports_weekly.html",
            {"report": report},
        )

    @router.get("/usage", response_class=HTMLResponse)
    async def model_usage_page(
        request: Request,
        window_hours: int = DEFAULT_SUMMARY_WINDOW_HOURS,
    ) -> HTMLResponse:
        hours = window_hours if window_hours >= 1 else DEFAULT_SUMMARY_WINDOW_HOURS
        report = request.app.state.audit_writer.model_usage(window_hours=hours)
        return templates.TemplateResponse(
            request,
            "usage.html",
            {
                "report": report,
                "window_hours": hours,
                "window_options": (24, 72, 168),
            },
        )

    def _policies_context(request: Request) -> dict[str, object]:
        engine = request.app.state.policy_engine
        config = engine.reload()
        return {"policies": config.policies}

    @router.get("/policies", response_class=HTMLResponse)
    async def policies_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "policies.html",
            _policies_context(request),
        )

    @router.get("/partials/policies", response_class=HTMLResponse)
    async def policies_partial(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "partials/policies_table.html",
            _policies_context(request),
        )

    @router.post("/policies/{policy_name}/enabled")
    async def set_policy_enabled_route(
        request: Request,
        policy_name: str,
        enabled: bool = Query(...),
    ) -> Response:
        engine = request.app.state.policy_engine
        config = engine.reload()
        known = {policy.name for policy in config.policies}
        if policy_name not in known:
            raise HTTPException(status_code=404, detail="Policy not found")

        set_policy_enabled(request.app.state.config_path, policy_name, enabled)
        engine.invalidate()
        # Keep app.state.config in sync for healthz / other readers.
        request.app.state.config = engine.reload()

        if request.headers.get("hx-request") == "true":
            return templates.TemplateResponse(
                request,
                "partials/policies_table.html",
                _policies_context(request),
            )
        return RedirectResponse(url="/policies", status_code=303)

    return router


def register_web(app: FastAPI) -> None:
    """Mount the dashboard. Requires Jinja2; callers should guard the import."""
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(create_web_router(build_templates()))
